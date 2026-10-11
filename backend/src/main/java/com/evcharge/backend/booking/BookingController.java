package com.evcharge.backend.booking;

import java.net.URI;
import java.util.List;

import jakarta.validation.Valid;
import jakarta.validation.constraints.Positive;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import com.evcharge.backend.booking.BookingDtos.BookingResponse;
import com.evcharge.backend.booking.BookingDtos.CreateBookingRequest;

@RestController
@RequestMapping("/api/bookings")
public class BookingController {

	private final BookingService service;

	public BookingController(BookingService service) {
		this.service = service;
	}

	@PostMapping
	public ResponseEntity<BookingResponse> create(@Valid @RequestBody CreateBookingRequest request) {
		BookingResponse created = service.create(request);
		return ResponseEntity.created(URI.create("/api/bookings/" + created.id())).body(created);
	}

	@GetMapping
	public List<BookingResponse> list(@RequestParam(required = false) @Positive Long stationId) {
		return service.list(stationId);
	}

	@GetMapping("/{id}")
	public BookingResponse get(@PathVariable @Positive Long id) {
		return service.get(id);
	}

	/**
	 * Cancels a booking (status becomes CANCELLED; the record is kept). 200 with the booking;
	 * 200 unchanged if already cancelled; 404 unknown id; 409 if the slot has already started.
	 */
	@PostMapping("/{id}/cancel")
	public BookingResponse cancel(@PathVariable @Positive Long id) {
		return service.cancel(id);
	}

}
