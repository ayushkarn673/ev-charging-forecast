package com.evcharge.backend.booking;

import java.time.Clock;
import java.time.Instant;
import java.util.List;

import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;

import com.evcharge.backend.booking.BookingDtos.BookingResponse;
import com.evcharge.backend.common.NotFoundException;
import com.evcharge.backend.common.SlotUnavailableException;
import com.evcharge.backend.pricing.SlotPricingService.SlotQuote;
import com.evcharge.backend.station.Station;
import com.evcharge.backend.station.StationRepository;

/**
 * The transactional part of booking: capacity check + insert. Kept separate from the HTTP call to
 * the ML service so that the station lock is never held while waiting on the network.
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
	 * one after another, then counts confirmed bookings in the slot. READ_COMMITTED makes that count
	 * see bookings committed by the previous lock holder, so capacity can never be exceeded.
	 */
	@Transactional(isolation = Isolation.READ_COMMITTED)
	public BookingResponse insert(Long stationId, String customerName, Instant start, SlotQuote quote) {
		Station station = stations.findByIdForUpdate(stationId)
			.orElseThrow(() -> new NotFoundException("Station " + stationId + " does not exist"));
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

}
