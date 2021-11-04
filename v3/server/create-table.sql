/*
 * Run as:
 *
 * sudo su postgres
 * psql -f create-table.sql
 */

/*
create user jelson;
grant all privileges on database airquality to jelson;
create database airquality;
*/

\c airquality

create table sensordatav4_sensors (
   "id" integer not null,
   "name" varchar not null,
   "ui_label" varchar not null,
   "location" point,
   "macaddr" varchar,
   primary key(id)
);

insert into sensordatav4_sensors (id, name, ui_label) values
   (1, 'jer-office', 'Jeremy - Office'),
   (2, 'jer-bedroom', 'Jeremy - Bedroom'),
   (50, 'gracie-bedroom', 'Gracie - Bedroom'),
   (100, 'dave-office', 'Dave - Office'),
   (101, 'dave-shed', 'Dave - Shed'),
   (150, 'jon-basement', 'Jon - Basement')
;

create table sensordatav4_types (
   "id" integer not null,
   "name" varchar not null,
   primary key(id)
);

insert into sensordatav4_types (id, name) values
   (10001, 'pm1.0'),
   (10002, 'pm2.5'),
   (10003, 'aqi2.5'),
   (10004, 'pm10.0'),
   (10005, 'temperature'),
   (10006, 'humidity')
;

create table sensordatav4 (
   "time" timestamptz not null,
   "sensorid" integer not null,
   "datatype" integer not null,
   "value" integer not null,
   constraint fk_sensorid foreign key(sensorid) references sensordatav4_sensors(id),
   constraint fk_datatype foreign key(datatype) references sensordatav4_types(id)
);

create index sensordatav4_time_idx on sensordatav4(time);
grant all on sensordatav4 to jelson;
grant all on sensordatav4_sensors to jelson;
grant all on sensordatav4_types to jelson;
create user grafana password 'i-love-data';
grant select on all tables in schema public to grafana;
grant select on sensordatav4 to grafana;
grant select on sensordatav4_types to grafana;
grant select on sensordatav4_sensors to grafana;
