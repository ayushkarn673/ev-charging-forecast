package com.evcharge.backend.booking;

import java.time.Instant;
import java.util.List;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import com.evcharge.backend.booking.BookingDtos.BookingResponse;
import com.evcharge.backend.booking.BookingDtos.CreateBookingRequest;
import com.evcharge.backend.common.NotFoundException;
import com.evcharge.backend.common.PriceChangedException;
import com.evcharge.backend.pricing.SlotPricingService;
import com.evcharge.backend.pricing.SlotPricingService.SlotQuote;
import com.evcharge.backend.station.Station;
import com.evcharge.backend.station.StationRepository;

@Service
public class BookingService {

	private final StationRepository stations;
	private final BookingRepository bookings;
	private final SlotRules slotRules;
	private final SlotPricingService pricing;
	private final BookingWriter writer;

	public BookingService(StationRepository stations, BookingRepository bookings, SlotRules slotRules,
			SlotPricingService pricing, BookingWriter writer) {
		this.stations = stations;
		this.bookings = bookings;
		this.slotRules = slotRules;
		this.pricing = pricing;
		this.writer = writer;
	}

	/**
	 * 1. validate the slot, 2. price it from the LSTM forecast (outside any transaction),
	 * 3. optionally check the price the customer saw, 4. lock + capacity check + insert.
	 */
	public BookingResponse create(CreateBookingRequest request) {
		Station station = stations.findById(request.stationId())
			.orElseThrow(() -> new NotFoundException("Station " + request.stationId() + " does not exist"));
		Instant start = slotRules.validateStart(station, request.startTime());
		SlotQuote quote = pricing.quote(station, start);
		if (request.quotedFinalPrice() != null
				&& request.quotedFinalPrice().compareTo(quote.price().finalPrice()) != 0) {
			throw new PriceChangedException("The price for this slot is now " + quote.price().finalPrice() + " "
					+ quote.currency() + " (you were shown " + request.quotedFinalPrice() + "). Please review it.");
		}
		return writer.insert(station.getId(), normalizeName(request.customerName()), start, quote);
	}

	/** Cancels a booking; see {@link BookingWriter#cancel(Long)} for the rules. */
	public BookingResponse cancel(Long bookingId) {
		return writer.cancel(bookingId);
	}

	/**
	 * Trims the name and collapses internal whitespace, so " Ravi  Kumar " and "Ravi Kumar" are the
	 * same customer for the duplicate check (case is ignored by the database collation).
	 */
	static String normalizeName(String customerName) {
		return customerName.strip().replaceAll("\\s+", " ");
	}

	@Transactional(readOnly = true)
	public List<BookingResponse> list(Long stationId) {
		List<Booking> result = stationId == null ? bookings.findAllByOrderByStartTimeAscIdAsc()
				: bookings.findByStationIdOrderByStartTimeAscIdAsc(stationId);
		return result.stream().map(BookingResponse::of).toList();
	}

	@Transactional(readOnly = true)
	public BookingResponse get(Long id) {
		return bookings.findById(id).map(BookingResponse::of)
			.orElseThrow(() -> new NotFoundException("Booking " + id + " does not exist"));
	}

}
