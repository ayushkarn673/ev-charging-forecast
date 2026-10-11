package com.evcharge.backend.station;

import java.util.List;
import java.util.Optional;

import jakarta.persistence.LockModeType;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface StationRepository extends JpaRepository<Station, Long> {

	List<Station> findAllByOrderByCodeAsc();

	/**
	 * Locks the station row ({@code SELECT ... FOR UPDATE}) until the transaction ends, so
	 * concurrent bookings for the same station are checked and inserted one at a time.
	 */
	@Lock(LockModeType.PESSIMISTIC_WRITE)
	@Query("select s from Station s where s.id = :id")
	Optional<Station> findByIdForUpdate(@Param("id") Long id);

}
