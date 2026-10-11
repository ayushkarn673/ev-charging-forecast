-- V2: demonstration stations for the UI, clearly marked as DEMO data (code prefix DEMO-).
-- They are not ACN-Data sites. Small capacities make "slot full" behaviour easy to show.
INSERT INTO stations (code, name, address, capacity, time_zone, base_price_per_hour, created_at) VALUES
    ('DEMO-01', 'Demo Station 01 - City Centre', 'Demonstration data - not a real location', 4, 'Asia/Kolkata', 120.00, UTC_TIMESTAMP(6)),
    ('DEMO-02', 'Demo Station 02 - Tech Park',   'Demonstration data - not a real location', 2, 'Asia/Kolkata', 150.00, UTC_TIMESTAMP(6)),
    ('DEMO-03', 'Demo Station 03 - Highway Hub', 'Demonstration data - not a real location', 6, 'Asia/Kolkata', 100.00, UTC_TIMESTAMP(6));
