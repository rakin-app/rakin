# Incident response: a personal-data breach on hosted Rakin

What the company does when hosted Rakin's personal data may have leaked, been changed or been lost. This is the runbook #369 asked for. It is an ops document, not legal text. The duties it carries out are in the [Términos de encargo](legal/terminos-de-encargo.md#12-vulneraciones-de-seguridad), clause 12. Their legal basis is [question 11](legal-research.md#11-breach-notice) of the legal research, and the gaps it closes are the [audit's "Breach response"](compliance-audit.md#breach-response).

The company is the **processor** (encargado). Each gym is the **controller** (responsable) of its members' data. So the company tells the gym, and the gym tells the Agencia and its members. The company drafts both of those messages for the gym.

## What counts

Count anything where personal data held for a gym may have been seen, copied, changed or destroyed by someone who should not have, or may have become unavailable. Some examples:

- a secret from `/srv/rakin/.env`, the deploy key, the backup key or a provider token is exposed: in a commit, a log, a screenshot, a chat or a lost laptop;
- someone other than the company signs in to the VPS, or to the R2, Resend, Sentry, Cloudflare or GitHub accounts;
- a bug shows one gym's data to another gym, or shows a member someone else's data;
- an email goes to the wrong person (a statement, a receipt, a sign-in link);
- a gym's staff account is taken over, for example through the owner's own email;
- the database or a bucket is lost and cannot be restored.

When in doubt, it counts. Every incident gets a [record](#7-the-record), including ones nobody is told about.

## 1. Who is on call

| Order | Who | How they hear |
| --- | --- | --- |
| 1 | The founder, who runs the server. On call at all times while the company is one person | Sentry and uptime alerts, `soporte@` and `hola@`, a gym's call, a provider's security email, GitHub secret scanning |
| 2 | Nobody yet. Add the second person here when there is one, and give them SSH, password manager and provider access first | |

Whoever learns of a possible incident tells the person on call at once, by phone if it is outside working hours. Learning of it starts the clock, so note the time.

## 2. The order: contain, scope, tell

**T0** is the moment someone at the company has reasonable grounds to think personal data was affected. Write it down first. Every deadline below counts from T0.

1. **Open the record** ([template](#7-the-record)) with T0 and what is known. Add to it as you go, with times.
2. **Preserve, then contain.** Containing can destroy evidence. A deploy, a rollback or a `docker compose up` that recreates a container **deletes that container's logs**. So save them first:

   ```sh
   cd /srv/rakin
   install -d -m 700 $HOME/incident-<yyyymmdd>
   docker compose logs --no-color --timestamps >$HOME/incident-<yyyymmdd>/compose.log
   cp releases.log $HOME/incident-<yyyymmdd>/
   ```

   If the host itself may be compromised, take a snapshot in the VPS provider's console before touching anything. Then contain, using the [playbook](#4-containing-by-kind) for the kind of incident.
3. **Scope.** Work out which gyms, which people, which data, and over what period, using the [sources](#3-scoping-what-exists-today). An estimate is enough to tell the gym. The scope can be refined after that.
4. **Tell each affected gym within 24 hours of T0**, using its [breach contact](#gym-breach-contacts) and the [notice](#6-the-notice-to-a-gym). If the company cannot tell which gyms are affected (for example, a secret that reaches every gym's data leaked), tell them all.
5. **Draft the Agencia report and the members' notice** for each gym, and send both to the gym with the notice or soon after it. The gym reports to the Agencia **within 72 hours** of the company's notice.
6. **Update** each gym as scope changes, and say when the next update is due.
7. **Close** the record: the cause, what was fixed, and the issues filed.

### Deadlines

| From → to | Deadline | Source |
| --- | --- | --- |
| Company → gym | within 24 hours of T0, updated as more is known | DPA clause 12; the law says only "deberá reportar" (art. 15 bis) |
| Gym → Agencia | within 72 hours of the company's notice, when there is a reasonable risk to the members' rights | DPA clause 12; the law says "sin dilaciones indebidas" (art. 14 sexies) |
| Gym → each affected member, through their guardian where there is one | without undue delay, aiming for the same 72 hours. Required when the breach touches payments and dues, children under 14 or sensitive data, so **for almost every Rakin breach** | art. 14 sexies, inciso 3 |
| Company → record | every incident, reported or not | DPA clause 12; art. 14 sexies |

The hours are a proposal until the lawyer confirms them ([item 3 (c)](legal-research.md#for-the-lawyer)). Leaving out a report or the record is *grave* (art. 34 ter k), and leaving one out on purpose is *gravísima* (art. 34 quáter f). By default the company sends the members' notice in the gym's name, unless the gym prefers to send it itself.

### Gym breach contacts

Each hosted gym's breach contact is kept **outside the app**, because an incident may take the app down or may involve the owner's own email:

- **Where:** the team's password manager, in one secure note per gym named `Rakin breach contact: <gym slug>`. This is the same vault that holds `.env` and the backup key, so whoever can respond can also read it, with the VPS, GitHub and the app all down. Never in this repo, its issues or the app.
- **What:** the gym's legal name and RUT, as on the DPA; a primary contact's name, role, email and phone; a second contact with a different email, where the gym has one; the date the DPA was signed; and the date the contact was last confirmed.
- **When:** taken from the DPA's signature page when the gym signs ([clause 12](legal/terminos-de-encargo.md#12-vulneraciones-de-seguridad) asks for it). Confirmed again every quarter, at the same time as the [restore rehearsal](deploy.md#restoring-to-check-a-backup), and whenever the gym's owner changes.
- **Cross-check, not source:** the controller contact in the gym's Ajustes (its privacy notice) should agree with it. Read it there only while the app is up.

Phone the primary contact as well as emailing them. If the incident may involve their email, use the phone only.

## 3. Scoping: what exists today

Nothing records reads today: there is no record of who opened a ficha, downloaded a proof or exported the ledger. #374 adds that. Until then, assume that anyone who had access saw everything that access allowed.

| Source | Where | Kept | Answers | Cannot answer |
| --- | --- | --- | --- | --- |
| Request logs | `docker compose logs api` (and `jobs`) on the VPS: JSON lines with `ts`, `method`, `path`, `status`, `duration_ms`, `request_id` | 5 × 20 MB per container (`deploy/docker-compose.yml`), so days at pilot traffic. **Lost when the container is recreated**, which happens on every deploy and rollback | which endpoints were hit, when, and errors | which gym (the host is not logged), which person, or which client IP. Caddy writes no access log |
| `auth_session` | Postgres: `person_id`, `email`, `gym_id`, `created_at`, `expires_at`, `ended_at` | never pruned | who had a session in which gym, and from when to when | IP, device or user agent, and what they did |
| `auth_link` | Postgres: the sign-in links issued, with `person_id`, `created_at` and `used_at` | never pruned | who asked for a link, and whether it was used | who opened it, or from where |
| `message_log` | Postgres: every email and `wa.me` message, with `gym_id`, `person_id`, `template`, `to_address`, `status`, `sent_at` and `payload` | never pruned | what went to which address, which is the scope of a misdirected email | whether it was read, or forwarded |
| `audit_event` | Postgres, append-only: deletions, corrections, reactivations, history edits, undone imports, with the actor | never pruned | who changed or deleted what | reads, exports, and ordinary edits |
| Sentry | the api's project: errors from the api, jobs and backups | the plan's retention: check it in the organisation's settings | when errors started, and which endpoints | anything that did not raise an error. **It is also a store of personal data**: until #373, errors carry request bodies and local variables |
| VPS | `journalctl -u ssh` (and `/var/log/auth.log`): SSH logins with user, key fingerprint and source IP. `releases.log`: every deploy. The provider's console: rescue mode, snapshots, firewall and console logins | journald and logrotate defaults: weeks | who reached the host, with which key, and from where | what they did there |
| R2 | Cloudflare's account audit log: tokens created or revoked, and bucket settings changed | Cloudflare's audit log retention | whether a token or a bucket's settings changed | which objects were read. R2 keeps no per-object access log |
| Resend | the dashboard's email list (to, subject, status) and API keys | the plan's data retention: short, so export early | what was sent, and with which key | anything older than the retention |
| GitHub | the org's audit log, and the `deploy` and `images` runs | GitHub's retention | who changed secrets, workflows or members, and what was deployed | anything on the host |
| Cloudflare | the account audit log: DNS and Email Routing changes | Cloudflare's retention | whether the gyms' hosts or `soporte@` were redirected | |

`TODO(owner)`: Sentry's retention, from the organisation's settings, goes in its row above.

Query Postgres on the host with `docker compose exec postgres psql -U rakin rakin`. That is the superuser, which sees past row-level security, so **write down every query in the record** and copy out only counts and ids, never names. Example: the sessions open in a window, per gym:

```sql
SELECT gym_id, count(*) FROM auth_session
WHERE created_at < '<end>' AND coalesce(ended_at, expires_at) > '<start>'
GROUP BY gym_id;
```

## 4. Containing, by kind

| Kind | Contain |
| --- | --- |
| A secret leaked | Rotate it, [below](#5-rotating-secrets), and look in its source's row above to see whether it was used |
| Host may be compromised (unknown SSH login, deploy key leaked, unexplained processes) | Snapshot first. Then assume everything in `.env` and on the disk leaked: rotate **every** secret, revoke the deploy key, and consider provisioning a new VPS and restoring the latest backup checked with `restore.sh` ([deploy.md](deploy.md#restoring-to-live)) instead of cleaning this one. To take the app offline for every gym: `docker compose stop caddy` |
| A release shows the wrong data | Save the logs, then `./deploy.sh --rollback <previous tag>` ([deploy.md](deploy.md#6-rollback)). Do not wait for a fix |
| A staff or member account taken over | End that person's sessions (below), and ask the gym to secure that email account before anyone signs in again |
| An email to the wrong person | Find every affected message in `message_log`, and stop the cause: the address on the ficha, or the job |
| Data lost | Check the latest backup with `restore.sh`, then restore to live ([deploy.md](deploy.md#restoring-to-live)). Everything since the last backup is lost: up to a day |

End one person's sessions, or everyone's:

```sql
UPDATE auth_session SET ended_at = now() WHERE ended_at IS NULL AND person_id = '<person id>';
UPDATE auth_session SET ended_at = now() WHERE ended_at IS NULL;   -- everyone, every gym
```

## 5. Rotating secrets

Generate each new value with `openssl rand -hex 32`, unless it says otherwise. Edit `/srv/rakin/.env` as `deploy`, update the copy in the password manager, and note the time in the record.

**`SECRET_KEY`** signs sign-in links and hashes sign-in codes (both valid for 15 minutes), and signs the unsubscribe links in sent emails, which never expire. **Rotating it does not sign anyone out**: session tokens are random and stored as a plain SHA-256, so to end sessions use the `UPDATE` above. Rotate with `docker compose up -d --wait api jobs`. Afterwards, pending sign-in links and codes fail, so people ask for a new one, and **every unsubscribe link in an email already sent stops working**. New emails carry new ones. Tell the gyms, so a member who complains is believed.

**`FIELD_ENCRYPTION_KEY`** seals sensitive custom field values (`person_field_value.secret`, AES-GCM, bound to the gym, the person and the field). On its own it exposes nothing: it matters together with a copy of the database or of a decrypted backup. **Changing it without re-sealing breaks things**: every sealed value fails to open, and the custom fields of everyone who has one fail to load, with an error. There is no re-sealing tool yet. Rotating it means a one-off script, run with the api and jobs stopped, that opens each row's `secret` with the old key and seals it with the new one in one transaction. File that as its own issue when it is needed. Keep the old key in the password manager, labelled with the date it was retired, for as long as any backup made under it exists: about 8 weeks (14 daily and 8 Sunday backups). A backup restored under the wrong key has those values unreadable.

**S3 keys for proofs** (`S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`). In R2, create a new token with Object Read & Write on the proofs bucket only. Put it in `.env`, run `docker compose up -d --wait api jobs`, then `docker compose run --rm api python -m app.blob_cors --check`, then **revoke the old token**. URLs already signed with the old token stop working when it is revoked, and they expire after `BLOB_URL_TTL_SECONDS` (15 minutes) anyway. Every gym's proofs are in this one bucket, so a token that could read it means telling every gym.

**Backup keys.** `BACKUP_S3_*` is rotated the same way, and restarted with `docker compose up -d --wait backup`, then `docker compose exec backup python -m app.backup list`. That token alone reveals nothing, because backups are encrypted to the age key, but it can delete them. So check that the list still has the 14 daily and 8 Sunday backups. **The age private key** is different: whoever has it and the backups can read every gym's data. If it leaks, make a new pair (`age-keygen`, [deploy.md](deploy.md#setting-them-up)), set the new `BACKUP_AGE_RECIPIENT`, run `docker compose up -d --wait backup` and `docker compose exec backup python -m app.backup run`, and rotate the backup token too. Delete the backups made under the old key only once enough new ones exist to restore from. A copy someone already made cannot be taken back, so that is also a notice to every gym.

**Database passwords.** Postgres is not reachable from the internet, so a leaked password matters only with access to the host, which is the bigger incident. For the app's two roles, change `POSTGRES_API_PASSWORD` and `POSTGRES_OWNER_PASSWORD` in `.env`, then run `docker compose run --rm migrate`, whose bootstrap re-sets the passwords of roles that already exist, then `docker compose up -d --wait`. The superuser's password (`POSTGRES_PASSWORD`) is read only when the database is created. Change it with `docker compose exec postgres psql -U rakin -c '\password rakin'`, then put the same value in `.env`, because `migrate` and `backup` connect with it, and run `docker compose up -d --wait`.

**The deploy key.** The deploy user is in the `docker` group, which is root on the host, so treat a leaked deploy key as a host compromise. On a laptop, run `ssh-keygen -t ed25519 -f rakin-deploy -C rakin-deploy -N ""`. Add the public half to the `deploy` user's `authorized_keys` from the admin account, set the private half with `gh secret set DEPLOY_SSH_KEY --repo rakin-app/rakin <rakin-deploy`, check that `ssh deploy@<host>` works with it, then **delete the old line** from `authorized_keys`. Check `journalctl -u ssh` for logins with the old key's fingerprint. An admin's personal key is replaced the same way, in their own `authorized_keys`.

**Others in `.env`.** `SMTP_PASSWORD` is a Resend API key: anyone who has it can send mail as `rakin.app` to the gyms' members, so revoke it in Resend and create a new one. `RESEND_WEBHOOK_SECRET` is rolled in the webhook's settings. `TURNSTILE_SECRET_KEY` is rolled in Cloudflare. `SENTRY_DSN` can only send events, so rotate it only if events are being forged. After each one, run `docker compose up -d --wait api jobs`.

## 6. The notice to a gym

In Spanish, by email to the breach contact and by phone. It has the four things clause 12 promises, and it is sent with what is known now: do not wait for the full scope.

```text
Asunto: [Rakin] Aviso de vulneración de seguridad: <academia>, <fecha>

Hola <nombre>:

Te escribimos como encargados del tratamiento de los datos de <academia> en Rakin,
según la cláusula 12 de los Términos de encargo.

Qué pasó: <qué, cuándo empezó, cuándo lo supimos (T0)>.
Qué datos y cuántas personas, aproximadamente: <categorías: contacto, pagos y deudas,
datos de menores, campos sensibles>; <número aproximado> personas.
Posibles consecuencias: <por ejemplo, correos falsos que se hagan pasar por la academia>.
Lo que ya hicimos: <contención, rotaciones, a qué hora>.

Lo que sigue:
- Adjuntamos un borrador del reporte a la Agencia de Protección de Datos Personales.
  La academia lo envía dentro de 72 horas desde este aviso.
- Adjuntamos un borrador del aviso a los alumnos y apoderados afectados. Si nos dices que
  sí, lo enviamos en nombre de la academia; si prefieres enviarlo tú, también está bien.
- Te enviaremos una actualización antes de <fecha y hora>, o antes si sabemos algo más.

Para cualquier pregunta: <nombre de quien atiende>, <teléfono>, soporte@rakin.app.

<firma>
```

The draft for the Agencia and the draft for the members reuse the record's fields. The members' notice says, in plain words, what happened, what data of theirs, what it could mean for them, what was done, what they can do (for example, distrust messages asking for payment to a new account), and who to ask at the gym. For a minor, it goes to the guardian.

## 7. The record

One per incident, **notified or not**, in the private `rakin-app/ops` repo, as an issue labelled `incident`. Never in this public repo. The record holds counts, categories and ids, never members' names. Records are never deleted.

```markdown
## Incident <yyyy-mm-dd>-<n>

- **T0** (we knew): <date, time, timezone>; how we learned: <alert, gym, member, provider>
- **Period affected**: <from> to <to>
- **Nature**: <what happened; confidentiality, integrity or availability>
- **Gyms affected**: <slugs>
- **Data categories**: <contact, payments and dues, minors, sensitive fields, proofs, …>
- **People affected, approximately**: <per gym>
- **Effects, likely and seen**: <…>
- **Measures**: <each containment and rotation, with its time>
- **Queries and sources used**: <each SQL query, log and console read>

### Notices
| To | When | By | Notes |
| --- | --- | --- | --- |
| <gym> | <time> | <who> | 24 h deadline: <T0 + 24 h> |
| Agencia, by <gym> | | | 72 h deadline: <notice + 72 h> |
| Members of <gym> | | | <sent by the company in the gym's name, or by the gym> |

If not reported: why (<no reasonable risk to members' rights, because …>).

### Closing
- **Cause**: <…>
- **Fixed by**: <PRs, issues>
- **What this runbook lacked**: <…>
```

## 8. Tabletop exercises

Read this runbook once, end to end, against one scenario, before the second gym onboards and once a year after. Time each step, look up each contact and source for real (without changing anything), and note in the table what was missing or wrong. Fix the runbook in the same week. Scenarios to rotate through:

1. A laptop with the deploy key is lost on a Friday night.
2. A release shows gym A's member list to gym B's coach for two hours.
3. A gym owner's email is taken over, and the attacker signs in to Rakin.
4. `.env` is pasted into a public issue.
5. A batch of statements goes to the wrong guardians.

| Date | Scenario | Who | Took | What changed |
| --- | --- | --- | --- | --- |
