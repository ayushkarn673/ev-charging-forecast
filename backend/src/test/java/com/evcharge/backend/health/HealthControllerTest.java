package com.evcharge.backend.health;

import static org.hamcrest.Matchers.not;
import static org.hamcrest.Matchers.containsString;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.BDDMockito.given;
import static org.mockito.Mockito.mock;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.sql.Connection;
import java.sql.SQLException;

import javax.sql.DataSource;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.webmvc.test.autoconfigure.WebMvcTest;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

/** Web-layer tests with a mocked DataSource: no database needed. */
@WebMvcTest(HealthController.class)
class HealthControllerTest {

	@Autowired
	private MockMvc mvc;

	@MockitoBean
	private DataSource dataSource;

	@Test
	void healthReportsUp() throws Exception {
		mvc.perform(get("/api/health"))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.status").value("UP"))
			.andExpect(jsonPath("$.service").value("evcharge-backend"))
			.andExpect(jsonPath("$.timestamp").isNotEmpty());
	}

	@Test
	void databaseHealthIsUpWhenConnectionIsValid() throws Exception {
		Connection connection = mock(Connection.class);
		given(connection.isValid(anyInt())).willReturn(true);
		given(dataSource.getConnection()).willReturn(connection);

		mvc.perform(get("/api/health/db"))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.status").value("UP"))
			.andExpect(jsonPath("$.database").value("mysql"));
	}

	@Test
	void databaseHealthIsDownWhenConnectionIsInvalid() throws Exception {
		Connection connection = mock(Connection.class);
		given(connection.isValid(anyInt())).willReturn(false);
		given(dataSource.getConnection()).willReturn(connection);

		mvc.perform(get("/api/health/db"))
			.andExpect(status().isServiceUnavailable())
			.andExpect(jsonPath("$.status").value("DOWN"));
	}

	@Test
	void databaseFailureDoesNotLeakDetails() throws Exception {
		given(dataSource.getConnection())
			.willThrow(new SQLException("Access denied for user 'evcharge_app'@'host' jdbc:mysql://internal-host:3307"));

		mvc.perform(get("/api/health/db"))
			.andExpect(status().isServiceUnavailable())
			.andExpect(jsonPath("$.status").value("DOWN"))
			.andExpect(content().string(not(containsString("Access denied"))))
			.andExpect(content().string(not(containsString("jdbc:"))))
			.andExpect(content().string(not(containsString("evcharge_app"))));
	}

}
