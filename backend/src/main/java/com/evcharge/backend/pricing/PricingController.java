package com.evcharge.backend.pricing;

import java.time.OffsetDateTime;

import jakarta.validation.constraints.Positive;

import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import com.evcharge.backend.pricing.SlotPricingService.SlotQuote;

@RestController
@RequestMapping("/api/pricing")
public class PricingController {

	private final SlotPricingService pricing;

	public PricingController(SlotPricingService pricing) {
		this.pricing = pricing;
	}

	/** Price breakdown for one slot, computed from the LSTM forecast. Same calculation as booking. */
	@GetMapping("/quote")
	public SlotQuote quote(@RequestParam @Positive Long stationId,
			@RequestParam @DateTimeFormat(iso = DateTimeFormat.ISO.DATE_TIME) OffsetDateTime startTime) {
		return pricing.quote(stationId, startTime);
	}

}
