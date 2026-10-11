package com.evcharge.backend.health;

import java.sql.Connection;
import java.time.Instant;

import javax.sql.DataSource;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * Liveness endpoints. {@code /api/health} only reports that the backend is running;
 * {@code /api/health/db} checks database connectivity without exposing connection details.
 */
@RestController
@RequestMapping("/api/health")
public class HealthController {

	private static final Logger log = LoggerFactory.getLogger(HealthController.class);
	private static final int DB_CHECK_TIMEOUT_SECONDS = 2;

	private final DataSource dataSource;

	public HealthController(DataSource dataSource) {
		this.dataSource = dataSource;
	}

	public record HealthResponse(String status, String service, String timestamp) {
	}

	public record DatabaseHealthResponse(String status, String database, String timestamp) {
	}

	@GetMapping
	public HealthResponse health() {
		return new HealthResponse("UP", "evcharge-backend", Instant.now().toString());
	}

	@GetMapping("/db")
	public ResponseEntity<DatabaseHealthResponse> database() {
		boolean up;
		try (Connection connection = dataSource.getConnection()) {
			up = connection.isValid(DB_CHECK_TIMEOUT_SECONDS);
		}
		catch (Exception ex) {
			log.warn("Database health check failed: {}", ex.getClass().getSimpleName());
			up = false;
		}
		DatabaseHealthResponse body = new DatabaseHealthResponse(up ? "UP" : "DOWN", "mysql", Instant.now().toString());
		return ResponseEntity.status(up ? HttpStatus.OK : HttpStatus.SERVICE_UNAVAILABLE).body(body);
	}

}
