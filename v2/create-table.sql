/*
 * Run as:
 *
 * sudo su - postgres
 * psql -f create-table.sql
 */

create user jelson;
grant all privileges on database airquality to jelson;
create database airquality;
grant all on particulate to jelson;

\c airquality

create table particulate (
   time timestamptz not null,
   sensorid integer,
   pm10 integer,
   pm25 integer,
   pm100 integer,
   aqi integer
);

create user grafana password 'i-love-data';
grant select on all tables in schema public to grafana;
grant select on particulate to grafana;
