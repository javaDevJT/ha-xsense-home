#!/usr/bin/env python3
"""Remove workflow-run artifacts except bounded logs and compact H/C reports."""

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import io
import ipaddress
import json
import os
from pathlib import PurePosixPath
import re
import stat
import struct
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile
import zlib


API_ROOT = "https://api.github.com"
API_VERSION = "2022-11-28"
PAGE_SIZE = 100
MAX_ARTIFACTS = 1000
MAX_JSON_RESPONSE = 8 * 1024 * 1024
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_ARCHIVE_FILES = 64
MAX_ARCHIVE_TOTAL_BYTES = 32 * 1024 * 1024
MAX_LOG_FILE_BYTES = 8 * 1024 * 1024
MAX_REPORT_FILE_BYTES = 2 * 1024 * 1024
MAX_COMPRESSION_RATIO = 1000
MAX_REDIRECTS = 3
MAX_CLOCK_SKEW = timedelta(0)
MAX_RETENTION = timedelta(hours=24)
_CENTRAL_DIRECTORY_HEADER = struct.Struct("<4s6H3I5H2I")

_REPO_PART = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
_RUN_ID = re.compile(r"^[0-9]{1,20}$")
_HEX = re.compile(r"^(?:[A-Fa-f0-9]{40}|[A-Fa-f0-9]{64})$")
_SHA1 = re.compile(r"^[A-Fa-f0-9]{40}$")
_ALLOWED_TOOLS = {"grype", "trivy", "sarif", "gitleaks"}
_FINDING_REQUIRED = {"tool", "report", "severity", "id"}
_FINDING_OPTIONAL = {"package", "installedVersion", "fixedVersions", "locations"}


class JanitorError(Exception):
    """Raised when API scope or response validation fails."""


def _unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise JanitorError("JSON contains duplicate object keys")
        result[key] = value
    return result


def _reject_json_constant(_value):
    raise JanitorError("JSON contains a non-standard numeric value")


def _strict_json(raw):
    try:
        text = raw.decode("utf-8", errors="strict") if isinstance(raw, bytes) else raw
        return json.loads(text, object_pairs_hook=_unique_json_object,
                          parse_constant=_reject_json_constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise JanitorError("JSON is malformed or not UTF-8") from exc


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _text(value, *, max_length=4096, allow_empty=False):
    return (isinstance(value, str) and len(value) <= max_length and
            (allow_empty or bool(value.strip())) and "\x00" not in value)


def validate_repository(value):
    if not isinstance(value, str) or value.count("/") != 1:
        raise JanitorError("GITHUB_REPOSITORY must be owner/name")
    owner, name = value.split("/", 1)
    if (owner in (".", "..") or name in (".", "..") or
            not _REPO_PART.fullmatch(owner) or not _REPO_PART.fullmatch(name)):
        raise JanitorError("GITHUB_REPOSITORY contains invalid characters")
    return f"{owner}/{name}"


def validate_run_id(value):
    value = str(value)
    if not _RUN_ID.fullmatch(value):
        raise JanitorError("run ID must be a positive decimal integer")
    if int(value) < 1:
        raise JanitorError("run ID must be a positive decimal integer")
    return int(value)


def parse_timestamp(value):
    if not _text(value, max_length=64):
        raise JanitorError("timestamp is missing or malformed")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise JanitorError("timestamp is missing or malformed") from exc
    if parsed.tzinfo is None:
        raise JanitorError("timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def _object(value):
    return isinstance(value, dict)


def _source_matches_run(run, repository, run_id, allow_running):
    if not _object(run) or not _is_int(run.get("id")) or run["id"] != run_id:
        raise JanitorError("workflow run ID did not match the requested run")
    status = run.get("status")
    accepted = {"completed"}
    if allow_running:
        accepted.add("in_progress")
    if status not in accepted:
        raise JanitorError("workflow run is not completed (or explicitly current and running)")
    run_repository = run.get("repository")
    if (not _object(run_repository) or
            not _text(run_repository.get("full_name"), max_length=201) or
            run_repository["full_name"].casefold() != repository.casefold() or
            not _is_int(run_repository.get("id")) or run_repository["id"] < 1):
        raise JanitorError("workflow run repository did not match GITHUB_REPOSITORY")
    head_sha = run.get("head_sha")
    if not isinstance(head_sha, str) or not _HEX.fullmatch(head_sha):
        raise JanitorError("workflow run source revision is missing or invalid")
    event = run.get("event")
    if not _text(event, max_length=128):
        raise JanitorError("workflow run event is missing or invalid")
    created_at = parse_timestamp(run.get("created_at"))
    head_repository = run.get("head_repository")
    head_repository_id = None
    if head_repository is not None:
        if not _object(head_repository) or not _is_int(head_repository.get("id")):
            raise JanitorError("workflow run head repository is malformed")
        head_repository_id = head_repository["id"]
    return head_sha, event, created_at, run_repository["id"], head_repository_id


def _artifact_link_matches_run(artifact, run_id, repository, head_sha,
                               repository_id, head_repository_id):
    workflow_run = artifact.get("workflow_run")
    if not _object(workflow_run):
        return False
    linked_id = workflow_run.get("id")
    if not _is_int(linked_id) or linked_id != run_id:
        return False
    linked_sha = workflow_run.get("head_sha")
    if not isinstance(linked_sha, str) or linked_sha.casefold() != head_sha.casefold():
        return False
    linked_repository_id = workflow_run.get("repository_id")
    if not _is_int(linked_repository_id) or linked_repository_id != repository_id:
        return False
    linked_head_repository_id = workflow_run.get("head_repository_id")
    if (head_repository_id is not None and
            (not _is_int(linked_head_repository_id) or
             linked_head_repository_id != head_repository_id)):
        return False
    linked_repository = workflow_run.get("repository")
    if linked_repository is not None:
        if (not _object(linked_repository) or
                not _text(linked_repository.get("full_name"), max_length=201) or
                linked_repository["full_name"].casefold() != repository.casefold()):
            return False
    return True


def _retention_metadata_is_valid(artifact, now, run_created_at):
    if not isinstance(artifact.get("expired"), bool) or artifact["expired"]:
        return False
    try:
        created_at = parse_timestamp(artifact.get("created_at"))
        expires_at = parse_timestamp(artifact.get("expires_at"))
    except JanitorError:
        return False
    if created_at > now + MAX_CLOCK_SKEW:
        return False
    if created_at < run_created_at:
        return False
    if expires_at <= created_at or expires_at - created_at > MAX_RETENTION:
        return False
    if expires_at <= now:
        return False
    return True


def _plain_text_member(name):
    return name.lower().endswith((".log", ".txt"))


def _validate_central_directory(raw, directory_offset, directory_size, expected_entries):
    directory_end = directory_offset + directory_size
    cursor = directory_offset
    count = 0
    while cursor < directory_end:
        if count >= MAX_ARCHIVE_FILES or directory_end - cursor < _CENTRAL_DIRECTORY_HEADER.size:
            raise JanitorError("archive has an invalid or excessive ZIP directory")
        try:
            fields = _CENTRAL_DIRECTORY_HEADER.unpack_from(raw, cursor)
        except struct.error as exc:
            raise JanitorError("archive has an invalid or excessive ZIP directory") from exc
        if fields[0] != b"PK\x01\x02" or fields[10] < 1 or fields[13] != 0:
            raise JanitorError("archive has an invalid or excessive ZIP directory")
        record_size = _CENTRAL_DIRECTORY_HEADER.size + fields[10] + fields[11] + fields[12]
        if record_size > directory_end - cursor:
            raise JanitorError("archive has an invalid or excessive ZIP directory")
        cursor += record_size
        count += 1
    if cursor != directory_end or count != expected_entries:
        raise JanitorError("archive has an invalid or excessive ZIP directory")


def _safe_zip_members(raw):
    if not isinstance(raw, bytes) or len(raw) > MAX_ARCHIVE_BYTES:
        raise JanitorError("archive exceeds the compressed-size limit")
    eocd_offset = raw.rfind(b"PK\x05\x06", max(0, len(raw) - 65557))
    if eocd_offset < 0 or eocd_offset + 22 > len(raw):
        raise JanitorError("archive is missing a valid ZIP directory")
    try:
        (_, disk_number, directory_disk, disk_entries, total_entries,
         directory_size, directory_offset, comment_size) = struct.unpack_from(
            "<4s4H2LH", raw, eocd_offset)
    except struct.error as exc:
        raise JanitorError("archive is missing a valid ZIP directory") from exc
    if (disk_number != 0 or directory_disk != 0 or disk_entries != total_entries or
            total_entries == 0xFFFF or directory_size == 0xFFFFFFFF or
            directory_offset == 0xFFFFFFFF or total_entries < 1 or
            total_entries > MAX_ARCHIVE_FILES or
            eocd_offset + 22 + comment_size != len(raw) or
            directory_offset + directory_size > eocd_offset):
        raise JanitorError("archive has an invalid or excessive ZIP directory")
    _validate_central_directory(raw, directory_offset, directory_size, total_entries)
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw), "r")
    except (OSError, zipfile.BadZipFile, ValueError) as exc:
        raise JanitorError("archive is not a valid ZIP file") from exc

    with archive:
        infos = archive.infolist()
        if not infos or len(infos) > MAX_ARCHIVE_FILES:
            raise JanitorError("archive has an invalid file count")
        seen = set()
        total = 0
        for info in infos:
            name = info.filename
            original_name = getattr(info, "orig_filename", name)
            if (not name or "\x00" in original_name or name != original_name or
                    "\\" in name or name.startswith("/")):
                raise JanitorError("archive contains an unsafe path")
            path = PurePosixPath(name)
            normalized_path = name[:-1] if info.is_dir() and name.endswith("/") else name
            if (path.is_absolute() or len(path.parts) > 8 or
                    any(part in ("", ".", "..") for part in normalized_path.split("/"))):
                raise JanitorError("archive contains an unsafe path")
            if len(name) > 512:
                raise JanitorError("archive path exceeds the limit")
            key = name.casefold()
            if key in seen:
                raise JanitorError("archive contains duplicate paths")
            seen.add(key)
            if info.flag_bits & 0x1:
                raise JanitorError("archive contains an encrypted file")
            if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                raise JanitorError("archive uses an unsupported compression method")
            mode = (info.external_attr >> 16) & 0xFFFF
            file_type = stat.S_IFMT(mode)
            if file_type == stat.S_IFLNK or (file_type not in (0, stat.S_IFREG, stat.S_IFDIR)):
                raise JanitorError("archive contains a link or special file")
            if info.file_size < 0 or info.compress_size < 0:
                raise JanitorError("archive contains invalid size metadata")
            total += info.file_size
            if total > MAX_ARCHIVE_TOTAL_BYTES:
                raise JanitorError("archive exceeds the expanded-size limit")
            if info.file_size and info.file_size / max(info.compress_size, 1) > MAX_COMPRESSION_RATIO:
                raise JanitorError("archive exceeds the compression-ratio limit")
            if info.is_dir():
                continue
            yield archive, info


def _validated_member_data(archive, info, per_file_limit):
    if info.file_size > per_file_limit:
        raise JanitorError("archive member exceeds the file-size limit")
    try:
        with archive.open(info, "r") as member:
            data = member.read(per_file_limit + 1)
            if len(data) != info.file_size or len(data) > per_file_limit:
                raise JanitorError("archive member size did not match its header")
            if member.read(1):
                raise JanitorError("archive member exceeds the file-size limit")
            return data
    except (OSError, EOFError, RuntimeError, zipfile.BadZipFile, zipfile.LargeZipFile,
            NotImplementedError, ValueError, zlib.error) as exc:
        raise JanitorError("archive member failed integrity validation") from exc


def _validate_log_archive(raw):
    seen_file = False
    for archive, info in _safe_zip_members(raw):
        if info.is_dir():
            continue
        if not _plain_text_member(info.filename):
            raise JanitorError("log archive contains a non-log file")
        content = _validated_member_data(archive, info, MAX_LOG_FILE_BYTES)
        try:
            text = content.decode("utf-8", errors="strict")
        except UnicodeError as exc:
            raise JanitorError("log archive contains non-UTF-8 content") from exc
        if "\x00" in text:
            raise JanitorError("log archive contains binary content")
        seen_file = True
    if not seen_file:
        raise JanitorError("log archive contains no log files")


def _require_keys(value, required, optional=()):
    return (isinstance(value, dict) and required.issubset(value) and
            set(value).issubset(required | set(optional)))


def _validate_compact_report(raw, repository, head_sha, event):
    document = _strict_json(raw)
    allowed_root = {"schemaVersion", "reports", "findings", "repository", "revision",
                    "image", "platform"}
    if not _object(document) or not {"schemaVersion", "reports", "findings"}.issubset(document):
        raise JanitorError("security report is not a compact minimizer document")
    if not set(document).issubset(allowed_root):
        raise JanitorError("security report has unsupported fields")
    if not _is_int(document.get("schemaVersion")) or document["schemaVersion"] != 1:
        raise JanitorError("security report schema version is unsupported")
    if "repository" in document:
        if (not _text(document["repository"], max_length=201) or
                document["repository"].casefold() != repository.casefold()):
            raise JanitorError("security report repository did not match the workflow run")
    if "revision" in document:
        revision = document["revision"]
        if (not isinstance(revision, str) or not _HEX.fullmatch(revision) or
                (event.startswith("pull_request") and not _SHA1.fullmatch(revision)) or
                (not event.startswith("pull_request") and
                 revision.casefold() != head_sha.casefold())):
            raise JanitorError("security report revision did not match the workflow run")
    for metadata_key in ("image", "platform"):
        if metadata_key in document and not _text(document[metadata_key], max_length=4096):
            raise JanitorError(f"security report {metadata_key} metadata is invalid")

    reports = document["reports"]
    findings = document["findings"]
    if not isinstance(reports, list) or not reports or len(reports) > 128:
        raise JanitorError("security report list is invalid")
    if not isinstance(findings, list) or len(findings) > 10000:
        raise JanitorError("security findings list is invalid")

    allowed_reports = Counter()
    expected_counts = Counter()
    for report in reports:
        if not _require_keys(report, {"name", "tool", "highCriticalCount"}):
            raise JanitorError("security report entry has unsupported fields")
        if (not _text(report["name"], max_length=512) or "/" in report["name"] or
                "\\" in report["name"] or report["name"] in (".", "..")):
            raise JanitorError("security report entry name is invalid")
        if not isinstance(report["tool"], str) or report["tool"] not in _ALLOWED_TOOLS:
            raise JanitorError("security report entry tool is unsupported")
        if not _is_int(report["highCriticalCount"]) or report["highCriticalCount"] < 0:
            raise JanitorError("security report count is invalid")
        allowed_reports[(report["name"], report["tool"])] += 1

    for finding in findings:
        if not _require_keys(finding, _FINDING_REQUIRED, _FINDING_OPTIONAL):
            raise JanitorError("security finding has unsupported fields")
        if not isinstance(finding["tool"], str) or finding["tool"] not in _ALLOWED_TOOLS:
            raise JanitorError("security finding tool is unsupported")
        if (not _text(finding["report"], max_length=512) or
                not _text(finding["id"], max_length=4096)):
            raise JanitorError("security finding identity is invalid")
        if not isinstance(finding["severity"], str) or finding["severity"] not in ("HIGH", "CRITICAL"):
            raise JanitorError("security report contains a non-High/Critical finding")
        key = (finding["report"], finding["tool"])
        if key not in allowed_reports:
            raise JanitorError("security finding does not belong to a listed report")
        expected_counts[key] += 1
        for key_name in ("package", "installedVersion"):
            if key_name in finding and not _text(finding[key_name], max_length=4096):
                raise JanitorError("security finding text field is invalid")
        if "fixedVersions" in finding:
            versions = finding["fixedVersions"]
            if not isinstance(versions, list) or len(versions) > 256 or any(
                    not _text(value, max_length=4096) for value in versions):
                raise JanitorError("security finding fixedVersions is invalid")
        if "locations" in finding:
            locations = finding["locations"]
            if not isinstance(locations, list) or len(locations) > 256:
                raise JanitorError("security finding locations are invalid")
            for location in locations:
                if not _require_keys(location, set(), {"path", "target", "startLine", "endLine"}):
                    raise JanitorError("security finding location has unsupported fields")
                for text_key in ("path", "target"):
                    if text_key in location and not _text(location[text_key], max_length=4096):
                        raise JanitorError("security finding location text is invalid")
                for line_key in ("startLine", "endLine"):
                    if line_key in location and (not _is_int(location[line_key]) or
                                                  location[line_key] < 1):
                        raise JanitorError("security finding line number is invalid")
                if ("startLine" in location and "endLine" in location and
                        location["endLine"] < location["startLine"]):
                    raise JanitorError("security finding endLine precedes startLine")

    actual_counts = Counter()
    for report in reports:
        key = (report["name"], report["tool"])
        actual_counts[key] += report["highCriticalCount"]
    if actual_counts != expected_counts:
        raise JanitorError("security report counts do not match its findings")


def _validate_report_archive(raw, repository, head_sha, event):
    seen_file = False
    for archive, info in _safe_zip_members(raw):
        if info.is_dir():
            continue
        if not info.filename.lower().endswith(".json"):
            raise JanitorError("security archive contains a non-JSON file")
        content = _validated_member_data(archive, info, MAX_REPORT_FILE_BYTES)
        _validate_compact_report(content, repository, head_sha, event)
        seen_file = True
    if not seen_file:
        raise JanitorError("security archive contains no compact reports")


def classify_artifact(artifact, raw_archive, repository, head_sha, event, run_id, now,
                      repository_id, head_repository_id=None, run_created_at=None):
    if not _object(artifact):
        return False, "malformed_metadata"
    artifact_id = artifact.get("id")
    if not _is_int(artifact_id) or artifact_id < 1:
        return False, "malformed_metadata"
    name = artifact.get("name")
    if not isinstance(name, str):
        return False, "unknown_name"
    if not name.startswith(("ci-log-", "security-high-critical-")):
        return False, "unknown_name"
    if not _artifact_link_matches_run(artifact, run_id, repository, head_sha,
                                      repository_id, head_repository_id):
        return False, "source_mismatch"
    if run_created_at is None or not _retention_metadata_is_valid(
            artifact, now, run_created_at):
        return False, "retention_invalid"
    if not _is_int(artifact.get("size_in_bytes")) or artifact["size_in_bytes"] < 0:
        return False, "size_invalid"
    if artifact["size_in_bytes"] > MAX_ARCHIVE_BYTES:
        return False, "size_limit"
    if not isinstance(raw_archive, bytes):
        return False, "download_failed"
    try:
        if name.startswith("ci-log-"):
            _validate_log_archive(raw_archive)
        else:
            _validate_report_archive(raw_archive, repository, head_sha, event)
    except JanitorError as exc:
        reason = str(exc)
        safe_reasons = {
            "archive exceeds the compressed-size limit": "size_limit",
            "archive exceeds the expanded-size limit": "expanded_size_limit",
            "archive member exceeds the file-size limit": "member_size_limit",
            "archive exceeds the compression-ratio limit": "compression_ratio_limit",
            "security report repository did not match the workflow run": "source_mismatch",
            "security report revision did not match the workflow run": "source_mismatch",
        }
        return False, safe_reasons.get(reason, "content_invalid")
    return True, "validated"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class GitHubApi:
    """Small REST client; only constructs URLs for the validated repository and IDs."""

    def __init__(self, token, opener=None):
        self._token = token
        self._opener = opener or urllib.request.build_opener(_NoRedirect())

    def _open(self, request):
        try:
            return self._opener.open(request, timeout=30)
        except urllib.error.HTTPError as exc:
            return exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise JanitorError("GitHub API request failed") from exc

    def _api_headers(self):
        return {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self._token}",
            "User-Agent": "ci-actions-artifact-janitor",
            "X-GitHub-Api-Version": API_VERSION,
        }

    @staticmethod
    def _read_limited(response, limit):
        content_length = response.headers.get("Content-Length")
        if content_length is not None:
            try:
                if int(content_length) > limit:
                    raise JanitorError("response exceeds the size limit")
            except ValueError as exc:
                raise JanitorError("response has invalid size metadata") from exc
        data = response.read(limit + 1)
        if len(data) > limit:
            raise JanitorError("response exceeds the size limit")
        return data

    def _request_json(self, method, url):
        request = urllib.request.Request(url, headers=self._api_headers(), method=method)
        response = self._open(request)
        try:
            status = getattr(response, "status", getattr(response, "code", 0))
            if not 200 <= status < 300:
                raise JanitorError(f"GitHub API returned HTTP {status}")
            body = self._read_limited(response, MAX_JSON_RESPONSE)
        finally:
            response.close()
        return _strict_json(body) if body else None

    def get_workflow_run(self, repository, run_id):
        url = f"{API_ROOT}/repos/{repository}/actions/runs/{run_id}"
        return self._request_json("GET", url)

    def list_run_artifacts(self, repository, run_id):
        artifacts = []
        page = 1
        expected_total = None
        while True:
            query = urllib.parse.urlencode({"per_page": PAGE_SIZE, "page": page})
            url = f"{API_ROOT}/repos/{repository}/actions/runs/{run_id}/artifacts?{query}"
            response = self._request_json("GET", url)
            if not _object(response) or not isinstance(response.get("artifacts"), list):
                raise JanitorError("GitHub artifact-list response is malformed")
            total = response.get("total_count")
            if not _is_int(total) or total < 0:
                raise JanitorError("GitHub artifact-list total_count is invalid")
            if expected_total is None:
                expected_total = total
                if expected_total > MAX_ARTIFACTS:
                    raise JanitorError("workflow run exceeds the artifact-count limit")
            elif total != expected_total:
                raise JanitorError("workflow artifact count changed during pagination")
            batch = response["artifacts"]
            if len(batch) > PAGE_SIZE or len(artifacts) + len(batch) > MAX_ARTIFACTS:
                raise JanitorError("workflow run exceeds the artifact-count limit")
            artifacts.extend(batch)
            if len(artifacts) >= expected_total:
                break
            if not batch:
                raise JanitorError("workflow artifact pagination ended early")
            page += 1
        if len(artifacts) != expected_total:
            raise JanitorError("workflow artifact pagination was incomplete")
        return artifacts

    @staticmethod
    def _validate_download_url(url):
        try:
            parts = urllib.parse.urlsplit(url)
            port = parts.port
        except ValueError as exc:
            raise JanitorError("artifact redirect URL is invalid") from exc
        if (parts.scheme != "https" or not parts.hostname or parts.username is not None or
                parts.password is not None or parts.fragment or port not in (None, 443)):
            raise JanitorError("artifact redirect URL is not safe HTTPS")
        hostname = parts.hostname.rstrip(".").casefold()
        if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith(".localhost"):
            raise JanitorError("artifact redirect URL targets a local host")
        try:
            address = ipaddress.ip_address(hostname.strip("[]"))
        except ValueError:
            address = None
        if address is not None and (not address.is_global or address.is_multicast):
            raise JanitorError("artifact redirect URL targets a non-public address")
        return url

    def download_artifact(self, repository, artifact_id):
        url = f"{API_ROOT}/repos/{repository}/actions/artifacts/{artifact_id}/zip"
        request = urllib.request.Request(url, headers=self._api_headers(), method="GET")
        response = self._open(request)
        redirects = 0
        try:
            while True:
                status = getattr(response, "status", getattr(response, "code", 0))
                if status in (301, 302, 303, 307, 308):
                    location = response.headers.get("Location")
                    response.close()
                    if not location or redirects >= MAX_REDIRECTS:
                        raise JanitorError("artifact download redirect is missing or excessive")
                    next_url = urllib.parse.urljoin(url, location)
                    self._validate_download_url(next_url)
                    url = next_url
                    # Redirect destinations receive no GitHub credential, even when a host matches.
                    request = urllib.request.Request(
                        url, headers={"Accept": "application/octet-stream",
                                      "User-Agent": "ci-actions-artifact-janitor"}, method="GET")
                    response = self._open(request)
                    redirects += 1
                    continue
                if status != 200:
                    raise JanitorError(f"artifact download returned HTTP {status}")
                return self._read_limited(response, MAX_ARCHIVE_BYTES)
        finally:
            response.close()

    def delete_artifact(self, repository, artifact_id):
        url = f"{API_ROOT}/repos/{repository}/actions/artifacts/{artifact_id}"
        request = urllib.request.Request(url, headers=self._api_headers(), method="DELETE")
        response = self._open(request)
        try:
            status = getattr(response, "status", getattr(response, "code", 0))
            if status not in (204, 404):
                raise JanitorError(f"artifact deletion returned HTTP {status}")
        finally:
            response.close()


class Janitor:
    def __init__(self, api, repository, now=None, log=None):
        self.api = api
        self.repository = validate_repository(repository)
        self.now = now or datetime.now(timezone.utc)
        self.log = log or (lambda _message: None)

    def cleanup(self, run_id, allow_running=False):
        run_id = validate_run_id(run_id)
        run = self.api.get_workflow_run(self.repository, run_id)
        head_sha, event, run_created_at, repository_id, head_repository_id = _source_matches_run(
            run, self.repository, run_id, allow_running)
        artifacts = self.api.list_run_artifacts(self.repository, run_id)
        kept = deleted = failures = 0
        for artifact in artifacts:
            artifact_id = artifact.get("id") if _object(artifact) else None
            if not _is_int(artifact_id) or artifact_id < 1:
                failures += 1
                self.log("error artifact_id=unknown reason=malformed_metadata")
                continue
            name = artifact.get("name")
            candidate = isinstance(name, str) and name.startswith(
                ("ci-log-", "security-high-critical-"))
            raw = None
            if candidate and _artifact_link_matches_run(
                    artifact, run_id, self.repository, head_sha, repository_id,
                    head_repository_id) and _retention_metadata_is_valid(
                        artifact, self.now, run_created_at) and _is_int(artifact.get("size_in_bytes")) and 0 <= artifact[
                            "size_in_bytes"] <= MAX_ARCHIVE_BYTES:
                try:
                    raw = self.api.download_artifact(self.repository, artifact_id)
                except JanitorError:
                    raw = None
            keep, reason = classify_artifact(artifact, raw, self.repository, head_sha, event,
                                              run_id, self.now, repository_id,
                                              head_repository_id, run_created_at)
            if keep:
                kept += 1
                self.log(f"keep artifact_id={artifact_id} reason={reason}")
                continue
            try:
                self.api.delete_artifact(self.repository, artifact_id)
                deleted += 1
                self.log(f"delete artifact_id={artifact_id} reason={reason}")
            except JanitorError:
                failures += 1
                self.log(f"error artifact_id={artifact_id} reason=delete_failed")
        self.log(f"summary run_id={run_id} artifacts={len(artifacts)} kept={kept} deleted={deleted} failures={failures}")
        return failures == 0


def _resolve_cli_target(args, environ):
    repository = validate_repository(environ.get("GITHUB_REPOSITORY", ""))
    if args.current:
        return repository, validate_run_id(environ.get("GITHUB_RUN_ID", "")), True
    return repository, validate_run_id(args.run_id), False


def main(argv=None, environ=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--current", action="store_true",
                      help="clean only GITHUB_RUN_ID; permits the run to still be in progress")
    mode.add_argument("--run-id", metavar="ID",
                      help="clean an exact run ID, which must already be completed")
    args = parser.parse_args(argv)
    environ = os.environ if environ is None else environ
    try:
        repository, run_id, allow_running = _resolve_cli_target(args, environ)
        token = environ.get("GH_TOKEN") or environ.get("GITHUB_TOKEN")
        if not _text(token, max_length=4096):
            raise JanitorError("GH_TOKEN or GITHUB_TOKEN is required")
        if any(character.isspace() for character in token):
            raise JanitorError("GitHub token contains invalid whitespace")
        def log(message):
            print(f"cleanup-actions-artifacts: {message}", file=sys.stderr)
        janitor = Janitor(GitHubApi(token), repository, log=log)
        if not janitor.cleanup(run_id, allow_running=allow_running):
            return 1
    except JanitorError as exc:
        print(f"cleanup-actions-artifacts: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
