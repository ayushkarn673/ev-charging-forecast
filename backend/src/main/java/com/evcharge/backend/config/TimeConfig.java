package com.evcharge.backend.config;

import java.time.Clock;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/** Single source of "now", so tests can fix the time. */
@Configuration(proxyBeanMethods = false)
public class TimeConfig {

	@Bean
	Clock clock() {
		return Clock.systemUTC();
	}

}
