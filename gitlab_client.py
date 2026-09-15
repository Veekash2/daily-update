"""Minimal GitLab REST client for pulling merged MRs / closed issues and open in-progress issues per user."""
import datetime as dt
import logging
import urllib.parse
import urllib.request
import json

log = logging.getLogger("onplia")


class GitLabError(Exception):
    pass


class GitLabClient:
    def __init__(self, base_url, token):
        self.base_url = base_url.rstrip("/")
        self.token = token

    def _get(self, path, params=None):
        url = f"{self.base_url}/api/v4{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params, doseq=True)
        req = urllib.request.Request(url, headers={"PRIVATE-TOKEN": self.token})
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "ignore")
            try:
                message = json.loads(body).get("message", body)
            except json.JSONDecodeError:
                message = body
            if e.code == 401:
                raise GitLabError("GitLab rejected the token (401 Unauthorized) — it is invalid, expired, or revoked.")
            if e.code == 403:
                raise GitLabError("GitLab token does not have permission for this (403 Forbidden). Check its scopes (needs at least read_api).")
            if e.code == 404:
                raise GitLabError(f"Not found (404) for {path}. If this was a project lookup, double check the project path is exactly right and your token can see it: {message}")
            raise GitLabError(f"GitLab API error {e.code} for {path}: {message}")
        except urllib.error.URLError as e:
            raise GitLabError(f"Could not reach {self.base_url} — check the GitLab URL and your internet connection: {e.reason}")

    def _get_all_pages(self, path, params=None, max_pages=30):
        """Follows GitLab's page-based pagination until a short/empty page is returned."""
        params = dict(params or {})
        per_page = params.setdefault("per_page", 100)
        results = []
        page = 1
        while page <= max_pages:
            params["page"] = page
            batch = self._get(path, params)
            if not batch:
                break
            results.extend(batch)
            if len(batch) < per_page:
                break
            page += 1
        return results

    def validate_token(self):
        """Raises GitLabError with a clear message if the token is missing/invalid; else returns the user info."""
        if not self.token:
            raise GitLabError("No GitLab token entered.")
        try:
            return self._get("/user")
        except GitLabError as e:
            if "401" in str(e):
                raise GitLabError("GitLab token is invalid or expired.")
            raise

    def get_project_id(self, project_path):
        encoded = urllib.parse.quote(project_path, safe="")
        data = self._get(f"/projects/{encoded}")
        return data["id"]

    def list_project_members(self, project_id):
        members = self._get(f"/projects/{project_id}/members/all", {"per_page": 100})
        return [{"username": m["username"], "name": m["name"]} for m in members]

    def list_my_projects(self):
        """Every project the token can see (direct membership or via group access)."""
        projects = self._get_all_pages(
            "/projects",
            {"membership": "true", "order_by": "last_activity_at", "simple": "true"},
        )
        return [p["path_with_namespace"] for p in projects]

    def list_labels(self, project_id):
        labels = self._get_all_pages(
            f"/projects/{project_id}/labels",
            {"include_ancestor_groups": "true"},
        )
        return [l["name"] for l in labels]

    def merged_today(self, project_id, username, date=None, board_labels=None):
        """Issues/MRs merged on `date` (default today, local date) authored/assigned to username.

        board_labels is accepted for symmetry with the other queries but not applied here: MRs in
        this workflow aren't labeled the way issues are (the scope label lives on the issue an MR
        closes, not the MR itself), so filtering merge_requests by it server-side would silently
        drop every real merge. One project, one author, one day is scope enough on its own.
        """
        date = date or dt.date.today()
        start = dt.datetime.combine(date, dt.time.min).isoformat() + "Z"
        end = dt.datetime.combine(date, dt.time.max).isoformat() + "Z"

        params = {
            "state": "merged",
            "scope": "all",
            "author_username": username,
            "updated_after": start,
            "updated_before": end,
            "per_page": 100,
        }

        mrs = self._get(f"/projects/{project_id}/merge_requests", params)
        merged_mrs = [mr for mr in mrs if mr.get("merged_at") and start <= mr["merged_at"] <= end]

        # A merge train entry is functionally done: it passed review and is queued for the target
        # branch, waiting only on pipelines GitLab runs itself. Treated as merged rather than left
        # to show up nowhere (not "in progress" — nobody has anything left to do on it) or to
        # silently appear tomorrow once GitLab actually lands it, a day after the person's real work
        # on it finished.
        try:
            train_entries = self._get(f"/projects/{project_id}/merge_trains")
        except GitLabError:
            train_entries = []
        for entry in train_entries:
            mr = entry.get("merge_request") or {}
            if mr.get("author", {}).get("username") != username:
                continue
            # MRs in this workflow aren't labeled the way issues are (the board scope label lives
            # on the issue, not the MR that closes it), so author + one project is scope enough —
            # unlike merged_today just above, which can lean on the merge_requests endpoint's own
            # label filter because it's asking GitLab to do that match, not reading it back off a
            # summary object that may not carry labels at all.
            if mr.get("iid") not in {m["iid"] for m in merged_mrs}:
                mr = dict(mr)
                mr["title"] = f'{mr.get("title", "")} (queued in merge train)'
                merged_mrs.append(mr)

        return merged_mrs

    def get_work_item_statuses(self, project_path, iids):
        """Native Status widget values (e.g. "To do"/"In progress"/"Done") for the given issue
        IIDs, via GraphQL — the REST Issues API has no field for this at all. Returns {iid: name},
        omitting issues with no Status widget (older boards, or the field left unset).
        """
        if not iids:
            return {}
        url = f"{self.base_url}/api/graphql"
        query = """
        query($fullPath: ID!, $iids: [String!]) {
          project(fullPath: $fullPath) {
            workItems(iids: $iids) {
              nodes {
                iid
                widgets { type ... on WorkItemWidgetStatus { status { name } } }
              }
            }
          }
        }
        """
        payload = json.dumps({
            "query": query,
            "variables": {"fullPath": project_path, "iids": [str(i) for i in iids]},
        }).encode("utf-8")
        req = urllib.request.Request(
            url, data=payload,
            headers={"PRIVATE-TOKEN": self.token, "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.HTTPError, urllib.error.URLError) as e:
            log.warning("GraphQL status lookup failed: %s", e)
            return {}
        if data.get("errors"):
            log.warning("GraphQL status lookup errors: %s", data["errors"])
            return {}
        nodes = (((data.get("data") or {}).get("project") or {}).get("workItems") or {}).get("nodes") or []
        statuses = {}
        for node in nodes:
            for widget in node.get("widgets", []):
                if widget.get("type") == "STATUS" and widget.get("status"):
                    statuses[int(node["iid"])] = widget["status"]["name"]
        return statuses

    def in_progress_issues(self, project_id, project_path, username, labels=None, board_labels=None):
        """Open issues currently belonging to username on the board: their current state, not
        whether they were touched today. A card sits in "in progress" or "review" until someone
        moves it, so that column membership is itself the signal a daily update wants — not GitLab's
        personal event stream, which can be empty for a day someone worked entirely off-platform
        (paired locally, reviewed in a call) yet still owns several open cards.

        "Belonging to" a person is not just the GitLab Assignee field: this board's own workflow
        tags the person actively working a card via a `reviewing::<username>` label once it moves
        into a review column (e.g. #2207 is assigned to someone else but carries
        `reviewing::ntokozo_mahamba`), so assignee-only filtering silently drops everyone's review
        work. An issue counts if either signal points at the person — but the two signals need
        different confirmation, because this board mixes two independent mechanisms:

        - As Assignee, the card is only "in progress" if GitLab's native Status field (a separate
          Work Item widget, invisible to the REST Issues API and to any label) actually reads
          "In progress" — a card can be assigned and still sit untouched in "To do" with identical
          labels to one that's moving (#2149 vs #1606).
        - As reviewer (`reviewing::<username>` label), Status is not the signal: #2207 carries that
          status as "Done" yet is still actively under review per this team's own labels, so a
          `review-status::*` label being present is what counts instead.

        board_labels: labels that must ALL be present (e.g. ["team::thor"]) to scope to one board.
        """
        reviewing_label = f"reviewing::{username}".lower()

        def matches_signal(issue):
            """Returns 'assignee', 'reviewing', or None."""
            issue_labels = [lbl.lower() for lbl in issue.get("labels", [])]
            assignees = {a.get("username", "").lower() for a in issue.get("assignees", [])}
            if not assignees:
                assignee = issue.get("assignee") or {}
                if assignee.get("username"):
                    assignees = {assignee["username"].lower()}
            if username.lower() in assignees:
                return "assignee"
            if reviewing_label in issue_labels and any(
                lbl.startswith("review-status") for lbl in issue_labels
            ):
                return "reviewing"
            return None

        # The board itself filters Label=team::thor AND Iteration=Current together, not the label
        # alone: without this, a person's whole backlog under that label — including past sprints —
        # counts as "in progress" instead of only what the board actually shows right now.
        params = {"state": "opened", "per_page": 100, "iteration_id": "Current"}
        if board_labels:
            params["labels"] = ",".join(board_labels)

        try:
            assigned = self._get(f"/projects/{project_id}/issues", {**params, "assignee_username": username})
            reviewing = self._get(f"/projects/{project_id}/issues", {**params, "labels": ",".join(
                (board_labels or []) + [f"reviewing::{username}"]
            )})
        except GitLabError as e:
            # Older GitLab instances may not accept the "Current" special value; fall back to no
            # iteration filter rather than failing the whole update.
            log.warning("iteration_id=Current rejected (%s), retrying without it", e)
            del params["iteration_id"]
            assigned = self._get(f"/projects/{project_id}/issues", {**params, "assignee_username": username})
            reviewing = self._get(f"/projects/{project_id}/issues", {**params, "labels": ",".join(
                (board_labels or []) + [f"reviewing::{username}"]
            )})
        by_iid = {i["iid"]: i for i in assigned}
        by_iid.update({i["iid"]: i for i in reviewing})

        signals = {iid: matches_signal(issue) for iid, issue in by_iid.items()}
        candidates = {iid: issue for iid, issue in by_iid.items() if signals[iid]}
        assignee_iids = [iid for iid, signal in signals.items() if signal == "assignee"]
        statuses = self.get_work_item_statuses(project_path, assignee_iids)

        issues = []
        for iid, issue in candidates.items():
            if signals[iid] == "reviewing" or statuses.get(iid) == "In progress":
                issues.append(issue)
        log.debug(
            "%s: assigned=%d reviewing=%d candidates=%d statuses=%s kept=%s",
            username, len(assigned), len(reviewing), len(candidates), statuses, [i["iid"] for i in issues],
        )

        if not labels:
            return issues

        # No `or issues` fallback: a label filter that matches nothing used to return everything,
        # so a typo in a label silently widened the report to the whole backlog.
        label_set = {l.lower() for l in labels}
        return [
            i for i in issues
            if any(lbl.lower() in label_set for lbl in i.get("labels", []))
        ]
