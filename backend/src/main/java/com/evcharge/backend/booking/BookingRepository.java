package com.evcharge.backend.booking;

import java.time.Instant;
import java.util.List;
import java.util.Optional;

import jakarta.persistence.LockModeType;

import org.springframework.data.jpa.repository.EntityGraph;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Lock;
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

	/**
	 * True if this customer already holds a booking with the given status for this station and slot.
	 * The column collation (utf8mb4_0900_ai_ci) makes the name comparison case-insensitive.
	 */
	boolean existsByStationIdAndStartTimeAndStatusAndCustomerName(Long stationId, Instant startTime,
			BookingStatus status, String customerName);

	/** Locks the booking row (SELECT ... FOR UPDATE) so concurrent cancellations are serialised. */
	@Lock(LockModeType.PESSIMISTIC_WRITE)
	@Query("select b from Booking b where b.id = :id")
	Optional<Booking> findByIdForUpdate(@Param("id") Long id);

	@EntityGraph(attributePaths = "station")
	List<Booking> findAllByOrderByStartTimeAscIdAsc();

	@EntityGraph(attributePaths = "station")
	List<Booking> findByStationIdOrderByStartTimeAscIdAsc(Long stationId);

}
