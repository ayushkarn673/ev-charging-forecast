package com.evcharge.backend.forecast;

import java.net.http.HttpClient;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.format.DateTimeFormatter;
import java.util.List;
import java.util.Map;
import java.util.function.Supplier;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.http.MediaType;
import org.springframework.http.client.JdkClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.HttpClientErrorException;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;

import com.evcharge.backend.config.MlServiceProperties;
import com.evcharge.backend.forecast.ForecastDtos.MlHealth;
import com.evcharge.backend.forecast.ForecastDtos.NextHourRequest;
import com.evcharge.backend.forecast.ForecastDtos.NextHourResponse;

/**
 * HTTP client for the Python FastAPI service that owns the LSTM. All inference happens there; the
 * backend never loads the model. Connection problems and 5xx answers become
 * {@link ForecastUnavailableException}; 4xx answers become {@link ForecastRejectedException}.
 */
@Component
public class MlServiceClient {

	private static final Logger log = LoggerFactory.getLogger(MlServiceClient.class);
	private static final ParameterizedTypeReference<Map<String, Object>> JSON_OBJECT = new ParameterizedTypeReference<>() {
	};

	/** Always includes seconds (OffsetDateTime.toString() drops ":00"). */
	private static final DateTimeFormatter ISO_WITH_SECONDS = DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ssXXX");

	private final RestClient http;

	public MlServiceClient(MlServiceProperties properties) {
		// HTTP/1.1: the JDK client's default HTTP/2 upgrade (h2c) on plain HTTP makes uvicorn drop the POST body.
		HttpClient client = HttpClient.newBuilder()
			.version(HttpClient.Version.HTTP_1_1)
			.connectTimeout(properties.connectTimeout())
			.build();
		JdkClientHttpRequestFactory factory = new JdkClientHttpRequestFactory(client);
		factory.setReadTimeout(properties.readTimeout());
		this.http = RestClient.builder().baseUrl(properties.baseUrl().toString()).requestFactory(factory).build();
	}

	public NextHourResponse predictNextHour(OffsetDateTime forecastTime) {
		return call("/predict/next-hour", () -> http.post()
			.uri("/predict/next-hour")
			.contentType(MediaType.APPLICATION_JSON)
			.body(new NextHourRequest("caltech", ISO_WITH_SECONDS.format(forecastTime)))
			.retrieve()
			.body(NextHourResponse.class));
	}

	public MlHealth health() {
		return call("/health", () -> http.get().uri("/health").retrieve().body(MlHealth.class));
	}

	public Map<String, Object> modelInfo() {
		return call("/model-info", () -> http.get().uri("/model-info").retrieve().body(JSON_OBJECT));
	}

	public Map<String, Object> evaluation() {
		return call("/evaluation", () -> http.get().uri("/evaluation").retrieve().body(JSON_OBJECT));
	}

	public Map<String, Object> evaluationSeries(LocalDate from, LocalDate to) {
		return call("/evaluation/series", () -> http.get()
			.uri(b -> b.path("/evaluation/series").queryParam("start", from).queryParam("end", to).build())
			.retrieve()
			.body(JSON_OBJECT));
	}

	private <T> T call(String endpoint, Supplier<T> request) {
		try {
			T body = request.get();
			if (body == null) {
				throw new ForecastUnavailableException("ML service returned an empty response from " + endpoint, null);
			}
			return body;
		}
		catch (HttpClientErrorException ex) {
			throw rejected(endpoint, ex);
		}
		catch (RestClientException ex) {
			log.warn("ML service call {} failed: {}", endpoint, ex.getClass().getSimpleName());
			throw new ForecastUnavailableException("The forecasting service is not available", ex);
		}
	}

	/** Keeps FastAPI's own reason ({code, message} or a validation detail list) for the client. */
	private static ForecastRejectedException rejected(String endpoint, HttpClientErrorException ex) {
		String code = "ML_REQUEST_REJECTED";
		String message = "The forecasting service rejected the request (" + ex.getStatusCode().value() + ")";
		try {
			Map<String, Object> body = ex.getResponseBodyAs(JSON_OBJECT);
			if (body != null && body.get("message") instanceof String m) {
				message = m;
				code = String.valueOf(body.getOrDefault("code", code));
			}
			else if (body != null && body.get("detail") instanceof List<?> details && !details.isEmpty()
					&& details.get(0) instanceof Map<?, ?> first && first.get("msg") != null) {
				message = String.valueOf(first.get("msg"));
			}
		}
		catch (RuntimeException ignored) {
			// body was not JSON - keep the generic message
		}
		log.info("ML service rejected {}: {} {}", endpoint, ex.getStatusCode().value(), code);
		return new ForecastRejectedException(code, message);
	}

}
