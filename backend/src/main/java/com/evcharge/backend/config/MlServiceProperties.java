package com.evcharge.backend.config;

import java.net.URI;
import java.time.Duration;

import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * Location of the Python FastAPI forecasting service (ml-service). Bound from
 * {@code evcharge.ml-service.*}; not called yet - used when the forecast client is added.
 */
@ConfigurationProperties("evcharge.ml-service")
public record MlServiceProperties(URI baseUrl, Duration connectTimeout, Duration readTimeout) {
}
