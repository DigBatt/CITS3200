// The vehicle filter.
//
// Renders the list from /api/vehicles.
//
// Also owns the liveness presentation: a vehicle the server reports as
// inactive is greyed AND labelled. The threshold comes from the server; this
// module never computes liveness.
//
// Clearing the filter restores the whole fleet.
