package com.evcharge.backend;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.net.URI;

import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.core.env.Environment;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.web.servlet.MockMvc;

import com.evcharge.backend.config.MlServiceProperties;

/**
 * Full application context against the Docker MySQL (127.0.0.1:3307 by default).
 * Runs only when DB_PASSWORD is provided, e.g. {@code .\scripts\with-db-env.ps1 mvn test}.
 * Read-only: no rows or tables are created by these tests.
 */
@SpringBootTest
@AutoConfigureMockMvc
@EnabledIfEnvironmentVariable(named = "DB_PASSWORD", matches = ".+")
class DatabaseIntegrationTests {

	@Autowired
	private MockMvc mvc;

	@Autowired
	private JdbcTemplate jdbc;

	@Autowired
	private Flyway flyway;

	@Autowired
	private Environment environment;

	@Autowired
	private MlServiceProperties mlService;

	@Test
	void connectsToTheApplicationDatabaseAsTheApplicationUser() {
		assertThat(jdbc.queryForObject("SELECT DATABASE()", String.class)).isEqualTo("ev_charging_db");
		assertThat(jdbc.queryForObject("SELECT CURRENT_USER()", String.class)).startsWith("evcharge_app@");
		assertThat(jdbc.queryForObject("SELECT @@version", String.class)).startsWith("8.4.");
	}

	@Test
	void databaseHealthEndpointIsUp() throws Exception {
		mvc.perform(get("/api/health/db"))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.status").value("UP"));
	}

	@Test
	void flywayHasRunAndCannotClean() {
		assertThat(flyway.getConfiguration().isCleanDisabled()).isTrue();
		assertThat(flyway.info().pending()).isEmpty();
		flyway.validate();
	}

	@Test
	void hibernateIsInValidateMode() {
		assertThat(environment.getProperty("spring.jpa.hibernate.ddl-auto")).isEqualTo("validate");
	}

	@Test
	void mlServiceUrlIsConfigurable() {
		assertThat(mlService.baseUrl()).isEqualTo(URI.create(environment.getProperty("ML_SERVICE_URL", "http://127.0.0.1:8000")));
		assertThat(mlService.connectTimeout()).isPositive();
		assertThat(mlService.readTimeout()).isPositive();
	}

}
