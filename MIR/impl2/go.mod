module mir1.dev/validate

// The tests compare this implementation against tables cut from the reference's
// Unicode data, so the floor is the Go release those tables were generated
// with. An older runtime folds a different set of code points and fails the
// differential test for a reason that is not in the format.
go 1.27
