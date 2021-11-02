/*
 * Run as:
 *
 * sudo su postgres
 * psql -f create-table.sql
 */

create user jelson;
grant all privileges on database airquality to jelson;
create database airquality;

\c airquality

create table particulatev3 (
   "time" timestamptz not null,
   "sensorid" integer,
   "pm1.0" integer,
   "pm2.5" integer,
   "pm10.0" integer,
   "aqi2.5" integer
);

create index time_idx on particulatev3(time);
grant all on particulatev3 to jelson;
create user grafana password 'i-love-data';
grant select on all tables in schema public to grafana;
grant select on particulatev3 to grafana;
