package com.evcharge.backend.booking;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;

/** Names are trimmed and internal whitespace collapsed before the duplicate check and storage. */
class CustomerNameNormalizationTest {

	@ParameterizedTest(name = "\"{0}\" -> \"{1}\"")
	@CsvSource(delimiter = '|', value = {
			"Ravi Kumar|Ravi Kumar",
			"'  Ravi Kumar  '|Ravi Kumar",
			"'Ravi    Kumar'|Ravi Kumar",
			"'  Ravi \t Kumar '|Ravi Kumar",
			"Priya|Priya" })
	void collapsesWhitespace(String input, String expected) {
		assertThat(BookingService.normalizeName(input)).isEqualTo(expected);
	}

}
