"""Case GLASS HARBOR — entirely fictional intrusion scenario for M04 / E03 / P02.

All organizations, people, domains and addresses are fabricated. Domains use the reserved ``.example``
TLD (RFC 2606) and IPs come from documentation ranges (RFC 5737: 192.0.2.0/24, 198.51.100.0/24,
203.0.113.0/24). Private RFC 1918 addresses are used for internal hosts.
"""

from __future__ import annotations

from datetime import datetime

CASE = {
    "code": "GLASS-HARBOR",
    "title": "Case GLASS HARBOR — Finance Share Exfiltration and Vendor Payment Fraud",
    "victim_organization": "Calder Ridge Freight Cooperative (fictional)",
    "summary": (
        "A regional freight cooperative reports that a large volume of finance files was downloaded from its "
        "cloud file service early on Saturday 18 October 2026, after an accounts-payable employee received "
        "repeated overnight sign-in approval prompts. Two days later, vendors began receiving fraudulent "
        "'updated remittance' emails that appeared to come from the cooperative's accounts-payable mailbox. "
        "The victim's managed service provider has supplied partial log exports. The external address seen in "
        "the logs belongs to a commercial hosting provider."
    ),
    "fictional_disclaimer": (
        "SYNTHETIC TRAINING SCENARIO. All persons, organizations, domains, addresses and records are fictional. "
        "Domains use the reserved .example TLD and IP addresses are documentation ranges. Any resemblance to "
        "real events is coincidental. Not derived from any investigative record."
    ),
    "instructor_overview": (
        "Learning purpose (M04/E03/P02): prioritize evidence sources and identify preservation, volatility, "
        "handling and referral considerations (C02, I02) and normalize/correlate indicators with provenance (A02). "
        "Seeded ambiguity: (1) MFA approval is suspected, not established; (2) firewall summary uses device-local "
        "Eastern time while other records are UTC and the victim is in Central time; (3) the 16 Oct laptop "
        "traffic to 192.0.2.88 is an unexplained lead, not an established infection vector; (4) the MSP "
        "removed the mailbox rule before preservation (INJ-01). Several retention windows (IdP 7 days, "
        "provider NetFlow 14 days, cloud audit 30 days) create urgency. Answer-key content is DEVELOPMENT "
        "PLACEHOLDER pending exercise-lead review (Action Register B09)."
    ),
}

SCENARIO_VERSION = "1.0-dev"


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


BASELINE_EVIDENCE = [
    {
        "code": "EV-001",
        "title": "Initial victim complaint",
        "source_type": "Victim complaint (intake form)",
        "observed_at": _dt("2026-10-19T14:12:00-05:00"),
        "observed_timezone": "America/Chicago",
        "observed_as_recorded": "10/19/2026 2:12 PM CDT (form submission time)",
        "provenance": (
            "Submitted through the (fictional) field office online complaint intake form by the victim "
            "organization's Controller. Logged by the intake duty agent as intake reference CR-2026-10-0419 "
            "(fictional)."
        ),
        "limitations": (
            "Victim's account, reconstructed from memory and an internal IT email. Times are approximate and "
            "stated in local time. Data volumes and losses are preliminary and unverified."
        ),
        "content": """COMPLAINT NARRATIVE (as submitted by victim)

On Saturday morning (Oct 18) our accounts payable clerk told us she received a lot of sign-in approval
prompts on her phone overnight and thinks she may have tapped "Approve" on one while half asleep.

On Monday our IT provider found that a large number of files were downloaded from our Finance shared
folder in the cloud early Saturday morning. The folder holds vendor banking details, vendor tax forms,
and payroll exports for about 140 employees.

On Monday afternoon two of our freight vendors called asking us to confirm "updated remittance
instructions" they had received by email from our AP mailbox. We did not send these.

We use CloudDrive Business (fictional) for files and email. Sign-in goes through Keystone Identity
(fictional). Our managed service provider, Harborline IT Services (fictional), runs our office firewall.

We have not paid anyone. We want to know what was taken and stop our vendors from being defrauded.

Reporting party:  Controller, controller@calderridge.example
Affected account: ap-clerk@calderridge.example
Office public IP: 198.51.100.14""",
        "instructor_notes": (
            "Facts vs assumptions: 'may have tapped Approve' is the clerk's belief, not established. Remittance "
            "emails suggest a business-email-compromise follow-on; mailbox access is not yet evidenced (see "
            "INJ-01). Employee payroll PII should be flagged as a privacy / victim-notification consideration "
            "for appropriate referral — students should not decide notification obligations themselves."
        ),
    },
    {
        "code": "EV-002",
        "title": "Cloud file service audit log excerpt",
        "source_type": "Cloud service audit log",
        "observed_at": _dt("2026-10-18T07:38:12+00:00"),
        "observed_timezone": "UTC",
        "observed_as_recorded": "2026-10-18T07:38:12Z (provider field TimeGenerated, UTC)",
        "provenance": (
            "Exported by the MSP administrator (admin@harborline-it.example) from the CloudDrive Business admin "
            "console on 2026-10-20 and emailed to the intake agent as a CSV attachment. Excerpt reproduced below."
        ),
        "limitations": (
            "Secondary copy handled by a third party; no hash or export manifest supplied. Excerpt only — full "
            "export not yet received. MSP states the tenant plan retains audit logs for 30 days (unverified). "
            "ClientIP is the address observed by the provider and may be a proxy or VPN egress point."
        ),
        "content": """CloudDrive Business — Tenant audit export (EXCERPT)   Tenant: calderridge.example
Export generated: 2026-10-20T15:02:44Z by admin@harborline-it.example

TimeGenerated (UTC)    User                          Operation               ClientIP        Detail
2026-10-18T07:38:12Z   ap-clerk@calderridge.example  SessionStarted          203.0.113.47    UserAgent: python-requests/2.31
2026-10-18T07:41:07Z   ap-clerk@calderridge.example  FileDownloaded          203.0.113.47    /Finance-Shared/Vendors/vendor_master_2026.xlsx
2026-10-18T07:41:09Z   ap-clerk@calderridge.example  FolderSyncStarted       203.0.113.47    /Finance-Shared/ (recursive)
2026-10-18T08:19:40Z   ap-clerk@calderridge.example  FolderSyncCompleted     203.0.113.47    1,284 items, 3.9 GB
2026-10-18T08:21:02Z   ap-clerk@calderridge.example  SessionEnded            203.0.113.47    —""",
        "instructor_notes": (
            "Retention: 30-day audit window from 18 Oct ends ~17 Nov — preservation and a native export with "
            "hash/manifest are expected. python-requests user agent suggests scripted bulk download (inference). "
            "Students must not infer the actor's location or identity from 203.0.113.47."
        ),
    },
    {
        "code": "EV-003",
        "title": "Identity provider sign-in record",
        "source_type": "Identity authentication log",
        "observed_at": _dt("2026-10-18T07:33:51+00:00"),
        "observed_timezone": "UTC",
        "observed_as_recorded": "2026-10-18T07:33:51Z (provider portal, UTC)",
        "provenance": (
            "Transcribed by the MSP from the Keystone Identity admin portal display (not a native export) and "
            "provided to the intake agent on 2026-10-20."
        ),
        "limitations": (
            "Manual transcription; errors possible. Provider location estimates are unreliable. MSP states the "
            "victim's license tier retains sign-in logs for 7 days (unverified) — earliest entries may already be "
            "unavailable. Does not show how or when the password was obtained."
        ),
        "content": """Keystone Identity — Sign-in activity (TRANSCRIBED)   User: ap-clerk@calderridge.example

Timestamp (UTC)        Result                 Factor           IP              Device
2026-10-17T21:02:17Z   Success                Push (approved)  198.51.100.14   CRF-LT-0112 (registered)
2026-10-18T07:21:04Z   MFA denied             Push             203.0.113.47    Unregistered
2026-10-18T07:23:40Z   MFA denied             Push             203.0.113.47    Unregistered
2026-10-18T07:26:12Z   MFA denied             Push             203.0.113.47    Unregistered
2026-10-18T07:28:55Z   MFA timed out          Push             203.0.113.47    Unregistered
2026-10-18T07:31:20Z   MFA denied             Push             203.0.113.47    Unregistered
2026-10-18T07:33:51Z   Success                Push (approved)  203.0.113.47    Unregistered
2026-10-18T07:36:30Z   New MFA method added   Authenticator    203.0.113.47    Unregistered
Note from MSP: password correct on all attempts above.""",
        "instructor_notes": (
            "Pattern consistent with MFA fatigue; password-compromise vector is an intelligence/investigative gap. "
            "7-day retention from 18 Oct means records may be lost by ~25 Oct — verify immediately and preserve. "
            "New MFA method = persistence concern; remediation belongs to the victim/MSP (referral), not the "
            "investigator."
        ),
    },
    {
        "code": "EV-004",
        "title": "Office firewall network activity summary",
        "source_type": "Network flow summary (MSP-prepared)",
        "observed_at": _dt("2026-10-17T02:14:09+00:00"),
        "observed_timezone": "America/New_York",
        "observed_as_recorded": "10/16/2026 22:14:09 (firewall device local time)",
        "provenance": (
            "Summary prepared by an MSP analyst from firewall CRF-FW01 logs and emailed on 2026-10-20. "
            "Underlying raw logs are held by the MSP."
        ),
        "limitations": (
            "Analyst-prepared summary, not raw logs; filtering thresholds chosen by the MSP. Firewall clock "
            "synchronization not confirmed. Timestamps are device-local Eastern time although the victim office "
            "is in Central time. MSP states firewall logs are kept 14 days."
        ),
        "content": """Harborline IT Services — Firewall flow summary for Calder Ridge Freight (prepared 10/20/2026)
Device: CRF-FW01        Log timezone setting: America/New_York (device local)
Window requested: 10/16/2026 00:00 – 10/19/2026 23:59 (device local)

Bulk outbound transfers > 50 MB, 10/18/2026 02:00–05:00 local:   NONE OBSERVED

Entries flagged by MSP analyst:
Local time            Internal host               Destination                         Port   Sessions  Out      In
10/16/2026 22:14:09   CRF-LT-0112 (10.20.4.112)   192.0.2.88                          8443   3         1.1 MB   14 KB   Category: Uncategorized
10/17/2026 17:02:17   CRF-LT-0112 (10.20.4.112)   login.keystone-id.example (198.51.100.30)  443  1   48 KB    210 KB  Category: Business
10/17/2026 17:05:40   CRF-LT-0112 (10.20.4.112)   files.clouddrive.example (198.51.100.10)   443  4   2.3 MB   61 MB   Category: Business

MSP analyst note: "No large data transfer from the office network during the incident window.
The download appears to have occurred off-network." CRF-LT-0112 is assigned to the AP clerk.""",
        "instructor_notes": (
            "Timezone trap: 17:02:17 EDT = 21:02:17Z, matching the legitimate office sign-in in EV-003. The "
            "16 Oct traffic to 192.0.2.88:8443 is an unexplained lead (possible credential-theft vector) — NOT "
            "established. Expected: preserve raw firewall logs before the 14-day window; consider preserving "
            "the laptop before any reimaging (volatility); route endpoint examination to a qualified examiner."
        ),
    },
    {
        "code": "EV-005",
        "title": "Hosting provider record retention note",
        "source_type": "Provider correspondence (retention statement)",
        "observed_at": _dt("2026-10-20T19:30:00+00:00"),
        "observed_timezone": "America/Los_Angeles",
        "observed_as_recorded": "10/20/2026 12:30 PM PDT (email sent time)",
        "provenance": (
            "Email reply from the provider's law-enforcement liaison mailbox to an informal inquiry from the case "
            "agent (fictional). Retention periods are the provider's own statements."
        ),
        "limitations": (
            "Informal correspondence, not a response to legal process. Does not identify which customer used the "
            "address at the relevant time. Retention statements unverified. Customer location unknown."
        ),
        "content": """From:    le-liaison@bluequill-hosting.example
Subject: RE: Inquiry regarding 203.0.113.47

Bluequill Hosting (fictional) confirms that 203.0.113.47 is within address space we assign to virtual
private server (VPS) customers. We do not provide customer information without appropriate legal process.

Our standard retention:
  - Subscriber and billing records ........ life of account + 2 years
  - VPS provisioning / IP assignment logs .. 90 days after the VPS is deprovisioned
  - Network flow (NetFlow) metadata ........ 14 days
  - Customer VPS disk contents ............. not accessed by Bluequill; deleted 7 days after deprovisioning

We will honor a valid preservation request for 90 days. Customers may deprovision at any time.
We serve customers in many countries.""",
        "instructor_notes": (
            "Decision points: urgency of a preservation request (14-day NetFlow from 18 Oct ends ~1 Nov; VPS may "
            "be deprovisioned at any time). Disclosure requires legal process — route to counsel; students must "
            "not assert which specific authority applies. Possible foreign customer → international cooperation "
            "referral consideration (bridges to M08)."
        ),
    },
]

INJECTS = [
    {
        "code": "INJ-01",
        "sequence": 1,
        "title": "Mailbox forwarding rule discovered",
        "approval_status": "approved",
        "student_briefing": (
            "SCENARIO UPDATE: The victim's MSP reports it found and removed a suspicious inbox rule on the "
            "accounts-payable mailbox. A mailbox audit excerpt has been added to the evidence library (EV-006)."
        ),
        "instructor_notes": (
            "Release after students have drafted initial priorities (~45 min into E03). Tests whether students "
            "revise priorities and recognize that remediation altered evidence before preservation."
        ),
        "evidence": [
            {
                "code": "EV-006",
                "title": "Mailbox audit — inbox rule creation and removal",
                "source_type": "Cloud mailbox audit log",
                "observed_at": _dt("2026-10-18T08:52:15+00:00"),
                "observed_timezone": "UTC",
                "observed_as_recorded": "2026-10-18T08:52:15Z (provider audit, UTC)",
                "provenance": (
                    "Exported by the MSP from the CloudDrive Business admin console on 2026-10-21, after the MSP "
                    "had already removed the rule."
                ),
                "limitations": (
                    "The rule was removed before preservation; forwarded message contents and the full set of "
                    "forwarded messages are unknown. The external address is at a free webmail service; the "
                    "account holder is unknown."
                ),
                "content": """CloudDrive Business — Mailbox audit (EXCERPT)   Mailbox: ap-clerk@calderridge.example

TimeGenerated (UTC)    Operation          ClientIP        Performed by                    Detail
2026-10-18T08:52:15Z   New-InboxRule      203.0.113.47    ap-clerk@calderridge.example    Name: "."
                        Conditions: subject or body contains "remittance", "invoice", "payment", "ACH"
                        Actions: forward to ar-dept.calderridge@freemail.example; move to "RSS Subscriptions";
                                 mark as read
2026-10-20T14:47:03Z   Remove-InboxRule   198.51.100.14   admin@harborline-it.example     Name: "." """,
                "instructor_notes": (
                    "Integrity: MSP remediation altered state before preservation. Expected: preservation request "
                    "to the webmail provider for the external account; consider financial-institution notification "
                    "routes for the fraudulent remittance requests. Analysts: 203.0.113.47 now links EV-002, EV-003 "
                    "and EV-006 — supports a single-actor session hypothesis but not identity."
                ),
            }
        ],
    },
    {
        "code": "INJ-02",
        "sequence": 2,
        "title": "Extortion email referencing payroll data",
        "approval_status": "draft",
        "student_briefing": (
            "SCENARIO UPDATE: The Controller forwards an email threatening to publish employee payroll data "
            "unless a payment is made."
        ),
        "instructor_notes": (
            "DRAFT — not yet approved by the content approver. Intended to bridge into M05 (virtual assets). "
            "Cannot be released until content approval is recorded."
        ),
        "evidence": [
            {
                "code": "EV-007",
                "title": "Extortion email (forwarded by victim)",
                "source_type": "Victim-forwarded email",
                "observed_at": _dt("2026-10-22T13:05:00+00:00"),
                "observed_timezone": "UTC",
                "observed_as_recorded": "Wed, 22 Oct 2026 13:05:00 +0000 (Date header)",
                "provenance": "Forwarded by the victim Controller; original headers not yet provided.",
                "limitations": "Forwarded copy; original message and full headers unavailable.",
                "content": """From: "Data Recovery Desk" <recovery-desk@freemail.example>
Subject: Your payroll files

We have 1,284 files from your finance share including payroll for your employees.
Payment instructions will follow. (Placeholder wallet: EXAMPLE-NOT-A-REAL-ADDRESS)""",
                "instructor_notes": "Draft inject content; pending approval.",
            }
        ],
    },
]
