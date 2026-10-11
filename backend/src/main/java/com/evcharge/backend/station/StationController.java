package com.evcharge.backend.station;

import java.math.BigDecimal;
import java.util.List;

import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import com.evcharge.backend.config.BookingProperties;

@RestController
@RequestMapping("/api/stations")
public class StationController {

	private final StationRepository stations;
	private final BookingProperties bookingProperties;

	public StationController(StationRepository stations, BookingProperties bookingProperties) {
		this.stations = stations;
		this.bookingProperties = bookingProperties;
	}

	public record StationResponse(Long id, String code, String name, String address, int capacity, String timeZone,
			BigDecimal basePricePerHour, String currency) {
	}

	@GetMapping
	@Transactional(readOnly = true)
	public List<StationResponse> list() {
		return stations.findAllByOrderByCodeAsc().stream()
			.map(s -> new StationResponse(s.getId(), s.getCode(), s.getName(), s.getAddress(), s.getCapacity(),
					s.getZoneId().getId(), s.getBasePricePerHour(), bookingProperties.currency()))
			.toList();
	}

}
