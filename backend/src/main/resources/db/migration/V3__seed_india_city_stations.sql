-- V3: one demonstration station in each city covered by the India demand model (Model insights page).
-- Like DEMO-01..03 these are sample stations, not real sites; existing stations and bookings are untouched.
-- Booking prices still use the backend's pricing service (Caltech-trained forecast), not the India model.
INSERT INTO stations (code, name, address, capacity, time_zone, base_price_per_hour, created_at) VALUES
    ('IN-PUN', 'EVCharge - Pune',      'Demonstration station in Pune - not a real location',      4, 'Asia/Kolkata', 120.00, UTC_TIMESTAMP(6)),
    ('IN-MUM', 'EVCharge - Mumbai',    'Demonstration station in Mumbai - not a real location',    4, 'Asia/Kolkata', 120.00, UTC_TIMESTAMP(6)),
    ('IN-DEL', 'EVCharge - Delhi NCR', 'Demonstration station in Delhi NCR - not a real location', 4, 'Asia/Kolkata', 120.00, UTC_TIMESTAMP(6)),
    ('IN-BLR', 'EVCharge - Bengaluru', 'Demonstration station in Bengaluru - not a real location', 4, 'Asia/Kolkata', 120.00, UTC_TIMESTAMP(6));
