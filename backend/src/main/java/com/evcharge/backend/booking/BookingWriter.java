package com.evcharge.backend.booking;

import java.time.Clock;
import java.time.Instant;
import java.util.List;

import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;

import com.evcharge.backend.booking.BookingDtos.BookingResponse;
import com.evcharge.backend.common.CancellationNotAllowedException;
import com.evcharge.backend.common.DuplicateBookingException;
import com.evcharge.backend.common.NotFoundException;
import com.evcharge.backend.common.SlotUnavailableException;
import com.evcharge.backend.pricing.SlotPricingService.SlotQuote;
import com.evcharge.backend.station.Station;
import com.evcharge.backend.station.StationRepository;

/**
 * The transactional parts of booking: duplicate + capacity check + insert, and cancellation. Kept
 * separate from the HTTP call to the ML service so that no lock is held while waiting on the network.
 */
@Component
public class BookingWriter {

	private final StationRepository stations;
	private final BookingRepository bookings;
	private final Clock clock;

	public BookingWriter(StationRepository stations, BookingRepository bookings, Clock clock) {
		this.stations = stations;
		this.bookings = bookings;
		this.clock = clock;
	}

	/**
	 * Locks the station row (SELECT ... FOR UPDATE) so concurrent requests for the same station run
	 * one after another, then checks for a duplicate and counts confirmed bookings in the slot.
	 * READ_COMMITTED makes both checks see bookings committed by the previous lock holder, so neither
	 * a duplicate nor more bookings than chargers can ever be stored.
	 */
	@Transactional(isolation = Isolation.READ_COMMITTED)
	public BookingResponse insert(Long stationId, String customerName, Instant start, SlotQuote quote) {
		Station station = stations.findByIdForUpdate(stationId)
			.orElseThrow(() -> new NotFoundException("Station " + stationId + " does not exist"));
		if (bookings.existsByStationIdAndStartTimeAndStatusAndCustomerName(stationId, start, BookingStatus.CONFIRMED,
				customerName)) {
			throw new DuplicateBookingException(customerName + " already has a confirmed booking at "
					+ station.getCode() + " for the slot starting " + start.atZone(station.getZoneId()).toOffsetDateTime());
		}
		Instant end = start.plus(HourlySlots.SLOT);
		List<Booking> overlapping = bookings.findOverlapping(stationId, BookingStatus.CONFIRMED, start, end);
		if (HourlySlots.bookedIn(start, overlapping) >= station.getCapacity()) {
			throw new SlotUnavailableException("All " + station.getCapacity() + " chargers at " + station.getCode()
					+ " are booked for the slot starting " + start.atZone(station.getZoneId()).toOffsetDateTime());
		}
		var price = quote.price();
		Booking booking = new Booking(station, customerName, start, end, price.basePrice(), price.multiplier(),
				price.finalPrice(), quote.currency(), price.utilization(), price.congestionLevel(),
				quote.forecast().mode(), quote.forecast().replayForecastTime().toInstant(), quote.forecast().modelId(),
				clock.instant());
		return BookingResponse.of(bookings.saveAndFlush(booking));
	}

	/**
	 * Cancels a booking: CONFIRMED becomes CANCELLED (the row is kept), which frees its charger
	 * because capacity counts only CONFIRMED bookings. Rules:
	 * <ul>
	 * <li>unknown id: {@link NotFoundException} (404)</li>
	 * <li>already CANCELLED: returned unchanged (idempotent, so a retried request is harmless)</li>
	 * <li>CONFIRMED but the slot has already started: {@link CancellationNotAllowedException} (409)</li>
	 * </ul>
	 * The booking row is locked for the duration of the transaction, so concurrent cancellations of
	 * the same booking are serialised.
	 */
	@Transactional(isolation = Isolation.READ_COMMITTED)
	public BookingResponse cancel(Long bookingId) {
		Booking booking = bookings.findByIdForUpdate(bookingId)
			.orElseThrow(() -> new NotFoundException("Booking " + bookingId + " does not exist"));
		if (booking.getStatus() == BookingStatus.CANCELLED) {
			return BookingResponse.of(booking);
		}
		if (!booking.getStartTime().isAfter(clock.instant())) {
			throw new CancellationNotAllowedException("Booking " + bookingId + " cannot be cancelled: its slot started at "
					+ booking.getStartTime().atZone(booking.getStation().getZoneId()).toOffsetDateTime());
		}
		booking.cancel();
		return BookingResponse.of(bookings.saveAndFlush(booking));
	}

}
