# Microsoft Teams channel notifications: feasibility study

**Project:** nUWAy Fleet Dashboard  
**Audience:** UWA REV Project  
**Status:** Preliminary assessment; no integration or client-tenant pilot has been completed

## 1. Purpose

This study assesses sending selected Fleet Dashboard updates to a Microsoft
Teams channel used by shuttle staff. The aim is to make operational and
reporting events easier to notice. Messages would link back to the dashboard,
where staff can check the current information and take any required action.

The scope is channel notifications only. Candidate events include new
pickup requests, changes in shuttle reporting status, daily snapshot results
and selected administrative changes. The client can choose which events are
useful enough to send.

## 2. Current system

Riders request pickup through the public website. The operator view shows how
many riders are waiting at each stop and refreshes every 10 seconds. The
dashboard also shows each shuttle's latest reported position. Administrators
record downtime and manage schedules. A separate live logger saves a daily
utilisation snapshot after Perth midnight; the system also records days for
which a snapshot is missing. No Teams notifications are sent today.

Pickup requests are stored in the web application's memory and disappear on
restart. Snapshots and their missing day records are saved to files. Snapshot
downloads and downtime details require admin sign-in. These differences affect
which alerts can be delivered reliably and what information can appear in a
staff channel.

## 3. Notification candidates

| Event | Suggested message | Value and qualification |
| --- | --- | --- |
| New pickup request | Stop, request time in Perth time, and operator view link. | Time sensitive, send only when a new request is created, not when the same open request is returned again. |
| Shuttle stops reporting | Vehicle, last seen time, and fleet view link. | Useful for awareness. Alert only after a sustained gap; send one message per outage rather than one per poll. A recovery message may help close the alert. |
| Daily snapshot saved | Reporting date and admin page link. | Lets staff know that the day's figures are ready. Send only after the snapshot file has been saved. |
| Daily snapshot missing | Reporting date and admin page link. | Draws attention to incomplete reporting. This is distinct from a snapshot that exists but contains unavailable metrics. |
| Downtime or schedule change | A brief description of the change and admin page link. | Optional. Managers may value it, but routine edits could generate too many messages. |

The recommended first pilot covers pickup requests and daily snapshot
outcomes. That tests both a live event from the web app and a scheduled event
from the logger. Fleet and administrative alerts can be added after operators
agree on their thresholds and value.

## 4. Proposed approach

Microsoft Teams Workflows can receive an HTTP webhook and post a message to a
channel. The client would create a Workflow for a private staff channel and
provide its webhook URL to the server. The web app would enqueue selected
pickup or administrative events. The logger would enqueue a snapshot outcome
when a file is saved or a missing day is recorded. A separate monitoring check
would be needed for shuttle status transitions: the existing API calculates
current status but does not currently emit alerts.

One sender could deliver events from both processes. Each event needs a stable
identifier to limit duplicates during retries or restarts; a webhook delivery
may still need manual reconciliation if its outcome is uncertain. Sending
should not delay a rider request or stop logger polling when Teams is
unavailable. The webhook URL must be stored as a server-side secret, outside
browser code and version control.

Messages should contain only the information staff need. They should not
include rider tokens, private review content, or restricted snapshot details.
A Teams message is an alert, not a live status display: a pickup request can
be cancelled or collected after the message is sent. Staff should follow the
link to check its current state. A snapshot message should say whether the
file is ready or missing; it should not present an unavailable metric as zero.

Microsoft recommends Workflows for new incoming webhooks as older Microsoft
365 Connectors approach retirement. Workflow ownership needs planning because
it is tied to users rather than owned by the channel itself. [Microsoft's
webhook guidance](https://learn.microsoft.com/en-us/microsoftteams/platform/webhooks-and-connectors/how-to/add-incoming-webhook)

## 5. Feasibility assessment

| Area | Assessment |
| --- | --- |
| Technical fit | **Feasible.** Pickup and snapshot events have identifiable points in the web app or logger. Shuttle status alerts require an additional monitoring check. |
| Reliability | **Requires work for operational use.** Persist pickup requests and pending alerts; add retries, deduplication, and delivery monitoring. The web app and logger must both be able to submit events. |
| Security and privacy | **Manageable.** Keep the webhook secret on the server, restrict channel membership, and link to the existing admin page for protected information. |
| Operator usefulness | **Needs a pilot.** Live alerts and daily reporting messages have different urgency. Operators should confirm which they will act on and whether the volume is acceptable. |
| Client dependencies | **Unconfirmed.** The client must confirm permission to create a Workflow, access to a suitable channel, and a person responsible for maintaining it. |
| Cost and effort | A basic pilot is a small integration task. Production work includes persistence, retries, monitoring, documentation, and operator testing. Any tenant or licensing costs need confirmation with the client. |

## 6. Pilot and success criteria

Use a test channel, test pickup requests  and a simulated day boundary. The
pilot should verify that:

1. A new pickup request produces one clear message with a working link; a
   repeated submission produces no duplicate.
2. A saved snapshot produces one ready message only after the file exists.
   A day recorded as missing produces one missing message. Both use the
   correct Perth reporting date.
3. Links show the current request or snapshot state, subject to the existing
   admin sign in where required.
4. A Teams outage does not prevent a rider request or stop logger polling;
   failed messages are recorded and can be retried.
5. Restarting either process does not lose open requests or pending alerts,
   and does not routinely resend alerts already delivered.
6. Operators find the messages useful and the channel's volume acceptable.

## 7. Conclusion and recommendation

**Feasible, subject to a tenant pilot and reliability work.** A Teams Workflow
offers a straightforward way to send pickup and daily snapshot notifications
to a staff channel. The project can run a limited pilot once the client grants
access to a channel and Workflow. Before relying on the notifications during
service, the project should persist pickup requests and add retryable,
monitored delivery shared by the web app and logger. Fleet status and admin
change alerts should follow only if staff confirm their value and alert rules.
The dashboard remains the source of current operational and reporting status.