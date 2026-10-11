package com.evcharge.backend;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.ConfigurationPropertiesScan;

@SpringBootApplication
@ConfigurationPropertiesScan
public class EvChargeBackendApplication {

	public static void main(String[] args) {
		SpringApplication.run(EvChargeBackendApplication.class, args);
	}

}
