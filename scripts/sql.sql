-- =====================================================================
--  Recruit · read-only queries for the live database
--  File: scripts/sql.sql      Database: data/db/recruit.db   (SQLite, WAL)
--
--  Run everything at once:
--      cd ~/Projects/recruit
--      sqlite3 -readonly data/db/recruit.db < scripts/sql.sql
--
--  Run one block:  copy it on a single line after the db path:
--      sqlite3 -readonly -header -column data/db/recruit.db "select * from app_state;"
--
--  The connection is mode=ro: nothing here can write.
--  Hashes are one-way — legacy plaintext columns in user_ids/entries are
--  blank on purpose, and no query can bring them back.
-- =====================================================================

.headers on
.mode column

-- ---------------------------------------------------------------------
-- 0 · what is in the database
-- ---------------------------------------------------------------------
select 'users'               as table_name, count(*) as rows from users
union all select 'ingested',            count(*) from ingested
union all select 'entries',             count(*) from entries
union all select 'user_ids',            count(*) from user_ids
union all select 'hits',                count(*) from hits
union all select 'push_subscriptions',  count(*) from push_subscriptions
union all select 'fcm_tokens',          count(*) from fcm_tokens
union all select 'password_resets',     count(*) from password_resets
union all select 'app_state',           count(*) from app_state;

-- ---------------------------------------------------------------------
-- 1 · users — accounts. password_hash is deliberately not selected.
-- ---------------------------------------------------------------------
select id,
       email,
       name,
       branch,
       division,
       is_admin                              as adm,
       email_verified                        as ver,
       email_bounced_at is not null          as bounced
from users
order by id;

-- ---------------------------------------------------------------------
-- 2 · app_state — one row: where the IMAP poller has got to.
-- ---------------------------------------------------------------------
select *
from app_state;

-- ---------------------------------------------------------------------
-- 3 · ingested — one row per CDC mail ever seen (msg_uid is unique).
-- ---------------------------------------------------------------------
select id,
       msg_uid                        as uid,
       kind,                          -- shortlist | announcement
       substr(subject, 1, 42)         as subject,
       date(created_at)               as seen
from ingested
order by id desc
limit 10;

-- ---------------------------------------------------------------------
-- 4 · entries — one row per code printed on a mail (164k rows total).
--     code_hash + the student's own sheet row (slot). Always limit.
-- ---------------------------------------------------------------------
select e.id,
       e.ingested_id                  as mail,
       substr(i.subject, 1, 26)       as subject,
       substr(e.code_hash, 1, 10)     as hash10,
       substr(e.slot, 1, 34)          as slot
from entries e
join ingested i on i.id = e.ingested_id
order by e.id desc
limit 10;

-- ---------------------------------------------------------------------
-- 5 · user_ids — which hashed code is watched by which account.
--     register_id / normalized_id are legacy blanks; code_hash is the record.
-- ---------------------------------------------------------------------
select ui.id,
       ui.user_id                         as usr,
       substr(u.email, 1, 24)             as email,
       substr(ui.code_hash, 1, 12)        as hash12,
       date(ui.created_at)                as added
from user_ids ui
join users u on u.id = ui.user_id
order by ui.user_id, ui.id;

-- how many codes each account tracks
select user_id as usr,
       count(*) as tracked
from user_ids
group by user_id
order by user_id;

-- ---------------------------------------------------------------------
-- 6 · hits — "this student's code was on this mail". read_at NULL = unread.
-- ---------------------------------------------------------------------
select h.id,
       substr(u.email, 1, 22)              as user,
       substr(i.subject, 1, 26)            as mail,
       case when h.read_at is null
            then 'unread' else 'read' end  as state,
       date(h.first_seen_at)               as seen
from hits h
join users u    on u.id = h.user_id
join ingested i on i.id = h.ingested_id
order by h.id desc
limit 12;

-- hits per account
select u.id,
       substr(u.email, 1, 30) as email,
       count(h.id)            as hits
from users u
left join hits h on h.user_id = u.id
group by u.id
order by hits desc;

-- ---------------------------------------------------------------------
-- 7 · push_subscriptions — browser (Web Push) devices, one row per profile.
-- ---------------------------------------------------------------------
select id,
       user_id                        as usr,
       platform,
       substr(endpoint, 1, 28)        as endpoint,
       date(created_at)               as added
from push_subscriptions
order by id;

-- ---------------------------------------------------------------------
-- 8 · fcm_tokens — Android devices (Firebase Cloud Messaging).
-- ---------------------------------------------------------------------
select id,
       user_id                        as usr,
       platform,
       substr(token, 1, 14)           as token,
       date(created_at)               as added
from fcm_tokens;

-- ---------------------------------------------------------------------
-- 9 · password_resets — token_hash only; used_at NULL = not yet spent.
-- ---------------------------------------------------------------------
select id,
       user_id                                       as usr,
       substr(token_hash, 1, 8)                      as hash8,
       created_at,
       expires_at,
       case when used_at is null then 'open'
            else 'spent' end                         as state
from password_resets
order by id desc;

-- ---------------------------------------------------------------------
-- 10 · integrity — proves no tracked ID is still stored as text.
--      Every value should be 0.
-- ---------------------------------------------------------------------
select 'entries.normalized_id'  as check_name, count(*) as offending from entries    where normalized_id != ''
union all select 'entries.original',           count(*) from entries    where original     != ''
union all select 'user_ids.normalized_id',     count(*) from user_ids   where normalized_id != ''
union all select 'user_ids.register_id',       count(*) from user_ids   where register_id   != ''
union all select 'hits not hashed',            count(*) from hits       where length(normalized_id) != 64
union all select 'entries without a hash',     count(*) from entries    where code_hash = ''
union all select 'user_ids without a hash',    count(*) from user_ids   where code_hash = '';
