package com.evcharge.backend.booking;

import java.time.Instant;
import java.util.List;

import org.springframework.data.jpa.repository.EntityGraph;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface BookingRepository extends JpaRepository<Booking, Long> {

	/** Bookings of a station with the given status that overlap [from, to). */
	@Query("""
			select b from Booking b
			where b.station.id = :stationId and b.status = :status
			  and b.startTime < :to and b.endTime > :from
			""")
	List<Booking> findOverlapping(@Param("stationId") Long stationId, @Param("status") BookingStatus status,
			@Param("from") Instant from, @Param("to") Instant to);

	@EntityGraph(attributePaths = "station")
	List<Booking> findAllByOrderByStartTimeAscIdAsc();

	@EntityGraph(attributePaths = "station")
	List<Booking> findByStationIdOrderByStartTimeAscIdAsc(Long stationId);

}
