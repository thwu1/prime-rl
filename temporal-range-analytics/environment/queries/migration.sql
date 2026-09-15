-- Server allocation migration: convert raw events into temporal allocations

CREATE TABLE allocations (
    server_id text NOT NULL,
    datacenter text NOT NULL,
    project_id int NOT NULL REFERENCES projects(id),
    validity daterange NOT NULL,
    daily_cost numeric(10,2) NOT NULL
);

INSERT INTO allocations (server_id, datacenter, project_id, validity, daily_cost)
SELECT server_id, datacenter, project_id,
       daterange(event_date, lead(event_date) OVER (ORDER BY event_date, server_id)),
       daily_cost
FROM raw_allocations;
