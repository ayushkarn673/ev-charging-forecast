package com.evcharge.backend.common;

import java.util.LinkedHashMap;
import java.util.Map;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.HttpStatusCode;
import org.springframework.http.ProblemDetail;
import org.springframework.http.ResponseEntity;
import org.springframework.validation.FieldError;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.context.request.WebRequest;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;
import org.springframework.web.servlet.mvc.method.annotation.ResponseEntityExceptionHandler;

import com.evcharge.backend.forecast.ForecastRejectedException;
import com.evcharge.backend.forecast.ForecastUnavailableException;

/**
 * Maps errors to RFC 9457 problem responses. Messages describe what the client must fix; database
 * errors and stack traces are never returned.
 */
@RestControllerAdvice
public class ApiExceptionHandler extends ResponseEntityExceptionHandler {

	private static final Logger log = LoggerFactory.getLogger(ApiExceptionHandler.class);

	@ExceptionHandler(NotFoundException.class)
	ProblemDetail notFound(NotFoundException ex) {
		return problem(HttpStatus.NOT_FOUND, "Not found", ex.getMessage());
	}

	@ExceptionHandler(BookingRejectedException.class)
	ProblemDetail rejected(BookingRejectedException ex) {
		return problem(HttpStatus.BAD_REQUEST, "Booking rejected", ex.getMessage());
	}

	@ExceptionHandler(SlotUnavailableException.class)
	ProblemDetail unavailable(SlotUnavailableException ex) {
		return problem(HttpStatus.CONFLICT, "Slot unavailable", ex.getMessage());
	}

	@ExceptionHandler(DuplicateBookingException.class)
	ProblemDetail duplicate(DuplicateBookingException ex) {
		return problem(HttpStatus.CONFLICT, "Duplicate booking", ex.getMessage());
	}

	@ExceptionHandler(CancellationNotAllowedException.class)
	ProblemDetail cancellationNotAllowed(CancellationNotAllowedException ex) {
		return problem(HttpStatus.CONFLICT, "Cancellation not allowed", ex.getMessage());
	}

	@ExceptionHandler(InvalidRequestException.class)
	ProblemDetail invalidRequest(InvalidRequestException ex) {
		return problem(HttpStatus.BAD_REQUEST, "Invalid request", ex.getMessage());
	}

	@ExceptionHandler(PriceChangedException.class)
	ProblemDetail priceChanged(PriceChangedException ex) {
		return problem(HttpStatus.CONFLICT, "Price changed", ex.getMessage());
	}

	@ExceptionHandler(ForecastUnavailableException.class)
	ProblemDetail forecastUnavailable(ForecastUnavailableException ex) {
		return problem(HttpStatus.SERVICE_UNAVAILABLE, "Forecast unavailable",
				ex.getMessage() + ". Start the ml-service (FastAPI) and try again.");
	}

	@ExceptionHandler(ForecastRejectedException.class)
	ProblemDetail forecastRejected(ForecastRejectedException ex) {
		ProblemDetail body = problem(HttpStatus.UNPROCESSABLE_CONTENT, "Forecast request rejected", ex.getMessage());
		body.setProperty("code", ex.getCode());
		return body;
	}

	@ExceptionHandler(MethodArgumentTypeMismatchException.class)
	ProblemDetail typeMismatch(MethodArgumentTypeMismatchException ex) {
		return problem(HttpStatus.BAD_REQUEST, "Invalid parameter",
				"Parameter '" + ex.getName() + "' has an invalid value");
	}

	@ExceptionHandler(Exception.class)
	ProblemDetail unexpected(Exception ex) {
		log.error("Unhandled error", ex);
		return problem(HttpStatus.INTERNAL_SERVER_ERROR, "Internal error", "An unexpected error occurred");
	}

	@Override
	protected ResponseEntity<Object> handleMethodArgumentNotValid(MethodArgumentNotValidException ex,
			HttpHeaders headers, HttpStatusCode status, WebRequest request) {
		Map<String, String> errors = new LinkedHashMap<>();
		for (FieldError error : ex.getBindingResult().getFieldErrors()) {
			errors.putIfAbsent(error.getField(), error.getDefaultMessage());
		}
		ProblemDetail body = problem(HttpStatus.BAD_REQUEST, "Validation failed", "One or more fields are invalid");
		body.setProperty("errors", errors);
		return ResponseEntity.badRequest().body(body);
	}

	private static ProblemDetail problem(HttpStatus status, String title, String detail) {
		ProblemDetail body = ProblemDetail.forStatusAndDetail(status, detail);
		body.setTitle(title);
		return body;
	}

}
