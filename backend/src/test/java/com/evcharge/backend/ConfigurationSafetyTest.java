package com.evcharge.backend;

import static org.assertj.core.api.Assertions.assertThat;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.List;

import org.junit.jupiter.api.Test;

/**
 * Guards the committed configuration: no password in application.yml and no setting that
 * would let Hibernate or Flyway change or wipe the database schema on its own.
 */
class ConfigurationSafetyTest {

	private static List<String> settingLines() throws IOException {
		try (InputStream in = ConfigurationSafetyTest.class.getResourceAsStream("/application.yml")) {
			assertThat(in).as("application.yml on the classpath").isNotNull();
			return new String(in.readAllBytes(), StandardCharsets.UTF_8).lines()
				.map(line -> line.replaceAll("\\s+#.*$", "").strip())
				.filter(line -> !line.isEmpty() && !line.startsWith("#"))
				.toList();
		}
	}

	@Test
	void passwordComesOnlyFromEnvironmentWithoutDefault() throws IOException {
		assertThat(settingLines()).filteredOn(line -> line.startsWith("password:"))
			.containsExactly("password: ${DB_PASSWORD}");
	}

	@Test
	void hibernateOnlyValidatesTheSchema() throws IOException {
		assertThat(settingLines()).contains("ddl-auto: validate")
			.noneMatch(line -> line.matches("ddl-auto:\\s*(create|create-drop|update|drop).*"));
	}

	@Test
	void serverBindsToLocalhostByDefault() throws IOException {
		assertThat(settingLines()).filteredOn(line -> line.startsWith("address:"))
			.containsExactly("address: ${SERVER_ADDRESS:127.0.0.1}");
	}

	@Test
	void databaseConnectionTimeoutsAreThirtySeconds() throws IOException {
		List<String> lines = settingLines();
		assertThat(lines).filteredOn(line -> line.startsWith("url: jdbc:mysql:"))
			.singleElement()
			.satisfies(url -> assertThat(url).contains("connectTimeout=30000", "socketTimeout=60000",
					"connectionTimeZone=UTC"));
		assertThat(lines).contains("connection-timeout: 30000");
	}

	@Test
	void flywayCleanIsDisabled() throws IOException {
		assertThat(settingLines()).contains("clean-disabled: true", "baseline-on-migrate: false");
	}

}
