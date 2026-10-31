#
# Copyright 2018 Red Hat, Inc.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
"""Creates the manifest file associated with the CUR."""

import json
import os
import re
from datetime import timedelta
from uuid import uuid4

import jinja2
from dateutil.relativedelta import relativedelta

TEMPLATE_DIR = os.path.dirname(__file__)
AWS_TEMPLATE_FILE = "aws-template-manifest.json"


def _manifest_datetime_str(date_time):
    """Format datetime as a string for manifest.

    Args:
        date_time (DateTime): Date Time to format to string
    Returns:
        (String): Formated date time string

    """
    return date_time.strftime("%Y%m%dT000000.000Z")


def _manifest_datetime_range(start, end):
    """Format datetime as a string for manifest.

    Args:
        start (DateTime): start date time
        end (DateTime): e d date time
    Returns:
        (String): Formated date time range

    """
    start_str = start.strftime("%Y%m%d")
    end_str = end.strftime("%Y%m%d")
    return f"{start_str}-{end_str}"


def aws_generate_manifest(fake, template_data):
    """Generate the manifest file.

    Args:
        fake (Obj): Used to create fake data
        template_data (Dict): data to render template with
    Returns:
        (String): S3 storage path
        (String): Rendered template data

    """
    start = template_data.get("start_date")
    report_name = template_data.get("aws_report_name")
    bp_start = start.replace(microsecond=0, second=0, minute=0, hour=0, day=1)
    bp_end = bp_start + relativedelta(months=+1)

    range_str = _manifest_datetime_range(bp_start, bp_end)
    assembly_id = uuid4()
    report_id = fake.sha256(raw_output=False)
    prefix_name = template_data.get("aws_prefix_name")
    file_names = template_data.get("file_names")
    report_keys = []
    for file_name in file_names:
        file_base_name = os.path.basename(file_name)
        if prefix_name:
            report_key = f"{prefix_name}/{report_name}/{range_str}/{assembly_id}/{file_base_name}.gz"
        else:
            report_key = f"/{report_name}/{range_str}/{assembly_id}/{file_base_name}.gz"
        report_keys.append(report_key)

    render_data = {
        "assembly_id": assembly_id,
        "report_id": report_id,
        "billing_period_start": _manifest_datetime_str(bp_start),
        "billing_period_end": _manifest_datetime_str(bp_end),
        "report_key": json.dumps(report_keys),
        "compression": "GZIP",
        "bucket": template_data.get("aws_bucket_name"),
    }
    render_data.update(template_data)
    template_loader = jinja2.FileSystemLoader(searchpath=TEMPLATE_DIR)
    template_env = jinja2.Environment(loader=template_loader)
    template = template_env.get_template(AWS_TEMPLATE_FILE)
    output = template.render(render_data)
    assembly_path = os.path.dirname(report_keys[0])
    return assembly_path, output


def ocp_generate_manifest(template_data):
    """Generate the manifest file.

    Args:
        template_data (Dict): data to render template with
    Returns:
        (String): Rendered template data

    """
    # template_data["cr_status"] = json.dumps(template_data["cr_status"], indent=2)
    return json.dumps(template_data, indent=2)


# Manifest cr_status template override (#726). A static-report template
# may carry a manifest.cr_status block that deep-merges over nise's
# hardcoded defaults — the W8/advisory parity fixtures need
# manifest.json files with cr_status.topology (hcpSnapshot entries
# carrying hostedClusterID, complete, observedAt, hcTier; the operator
# emission contract ros-ocp-backend's librobne/csv/manifest.go consumes).
#
# Relative markers: override string values shaped `now` or
# `now-<n><s|m|h|d>` resolve against the generation clock (UTC, RFC3339
# Z), so fixtures stay regenerable — generate today, consume today.
# Future offsets are deliberately not part of the grammar (fixtures look
# back); anything else passes through verbatim.

_MARKER_RE = re.compile(r"^now(?:-(\d+)([smhd]))?$")

_MARKER_UNITS = {
    "s": lambda n: timedelta(seconds=n),
    "m": lambda n: timedelta(minutes=n),
    "h": lambda n: timedelta(hours=n),
    "d": lambda n: timedelta(days=n),
}


def resolve_relative_markers(value, now):
    """Recursively resolve `now` / `now-<n><unit>` strings against now.

    Dicts and lists recurse; every other scalar passes through
    unchanged. The result never aliases the input.

    Args:
        value: the override value (any YAML shape)
        now (datetime): the resolution clock (aware, UTC)
    Returns:
        the value with markers resolved to RFC3339 Z timestamps
    """
    if isinstance(value, dict):
        return {k: resolve_relative_markers(v, now) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_relative_markers(v, now) for v in value]
    if isinstance(value, str):
        match = _MARKER_RE.match(value)
        if match:
            resolved = now
            if match.group(1):
                resolved = now - _MARKER_UNITS[match.group(2)](int(match.group(1)))
            return resolved.strftime("%Y-%m-%dT%H:%M:%SZ")
        return value
    return value


def _deep_merge(base, override):
    """Merge override into base: recursive on dicts, replacement otherwise.

    Lists (hcpSnapshot entries) and scalars are replaced wholesale —
    element-merging snapshot entries has no meaningful semantics.

    Args:
        base (dict): the hardcoded cr_status
        override (dict): the template's manifest.cr_status
    Returns:
        dict: a new merged mapping (inputs never mutated)
    """
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def apply_manifest_cr_status_override(base_cr_status, override, now):
    """Apply the template's manifest.cr_status override over the base.

    Markers resolve before merging (only override values carry markers;
    the base is already literal). A missing/empty override returns the
    base unchanged — existing templates produce today's manifest
    byte-identically.

    Args:
        base_cr_status (dict): the hardcoded cr_status block
        override (dict | None): the template's manifest.cr_status
        now (datetime): the marker resolution clock (aware, UTC)
    Returns:
        dict: the merged cr_status
    """
    if not override:
        return base_cr_status
    return _deep_merge(base_cr_status, resolve_relative_markers(override, now))
