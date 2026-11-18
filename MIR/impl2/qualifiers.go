package main

import "strings"

// MIR-1.2 record qualifiers, derived and report-only.
//
// The second implementation of MIR-1.2-Qualifiers.md. None of these values
// changes a check, a status, or an id; they name measurements the record already
// carries so that a reader does not have to recompute them.

// reportsNumber mirrors Python's isinstance(value, (int, float)) minus bool.
func reportsNumber(run *jobject, metric string) bool {
	result, ok := objectValue(getField(run, "result"))
	if !ok || metric == "" {
		return false
	}
	_, ok = numericValue(getField(result, metric))
	return ok
}

func recordQualifiers(record any) []string {
	object := asObject(record)
	runs, ok := asArray(getField(object, "runs"))
	if !ok || len(runs) == 0 {
		return nil
	}
	claim, _ := objectValue(getField(object, "claim"))
	behavior, _ := getField(claim, "behavior").(string)
	claimant, _ := objectValue(getField(object, "claimant"))
	operator, _ := getField(claimant, "operator").(string)
	funding := getField(claimant, "funding_source")

	out := []string{}
	baseline := false
	for _, raw := range runs {
		run, ok := objectValue(raw)
		if !ok {
			continue
		}
		if value, _ := run.get("intervention_hash"); value == nil {
			baseline = true
		}
	}
	if baseline {
		out = append(out, "baseline-present")
	}

	type population struct{ units, samples int64 }
	populations := map[population]bool{}
	known := true
	for _, raw := range runs {
		// Python filters non-object runs out before measuring populations, so a
		// null entry is skipped rather than treated as an unknown population.
		run, ok := objectValue(raw)
		if !ok {
			continue
		}
		result, ok := objectValue(getField(run, "result"))
		if !ok {
			known = false
			break
		}
		units, ok := integerValue(getField(result, "n_units"))
		if !ok || !units.IsInt64() {
			known = false
			break
		}
		samples, ok := integerValue(getField(result, "samples_per_unit"))
		if !ok || !samples.IsInt64() {
			known = false
			break
		}
		populations[population{units.Int64(), samples.Int64()}] = true
	}
	if known && len(populations) == 1 {
		out = append(out, "single-population")
	}

	other := []*jobject{}
	for _, raw := range runs {
		run, ok := objectValue(raw)
		if !ok {
			continue
		}
		if value, _ := run.get("intervention_hash"); value == nil {
			continue
		}
		value, ok := getField(run, "operator").(string)
		if !ok || strings.TrimSpace(operator) == "" {
			continue
		}
		if foldKey(value) == foldKey(operator) {
			continue
		}
		other = append(other, run)
	}

	unpriced := false
	for _, run := range other {
		if !disclosedRun(run) && reportsNumber(run, behavior) {
			unpriced = true
		}
	}
	if unpriced {
		out = append(out, "unpriced-reproduction")
	}

	counted := []*jobject{}
	if operator != "" && disclosed(funding) {
		for _, run := range other {
			if !disclosedRun(run) {
				continue
			}
			runFunding := getField(run, "funding_source")
			if !disclosed(runFunding) {
				continue
			}
			text, _ := runFunding.(string)
			claimFunding, _ := funding.(string)
			if foldKey(text) == foldKey(claimFunding) {
				continue
			}
			counted = append(counted, run)
		}
	}

	metrics := []string{}
	invariants, _ := asArray(getField(object, "invariants"))
	for _, raw := range invariants {
		item, ok := objectValue(raw)
		if !ok {
			continue
		}
		if metric, ok := getField(item, "metric").(string); ok {
			metrics = append(metrics, metric)
		}
	}
	if len(metrics) > 0 {
		for _, run := range counted {
			complete := true
			for _, metric := range metrics {
				if !reportsNumber(run, metric) {
					complete = false
					break
				}
			}
			if complete {
				out = append(out, "invariants-replicated")
				break
			}
		}
	}
	return out
}

// sameStrings compares two qualifier lists in order.
func sameStrings(left, right []string) bool {
	if len(left) != len(right) {
		return false
	}
	for i := range left {
		if left[i] != right[i] {
			return false
		}
	}
	return true
}
