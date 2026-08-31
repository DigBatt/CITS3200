
- Standardises benchmarks for accurate *Mobile Equipment* comparison between organisations

## Classification Layers
- Classification layer organises activities, statuses and events into time buckets + allowing for consistent Key Performance Indicators (KPIs)
- Operation must account for all time
- One-to-one 'time-category' linking with Calendar time as root
![[Pasted image 20260831143102.png]]

### Calendar Time
- All the time there is in the reporting window. 8,760 h per year, 8,784 in a leap year; the guideline treats the difference as negligible. Also called nominal time
* `timestamp`, `timestamp_unix`
### Scheduled Time
* Time the asset is required to meet the business plan and is assigned to an operation, project or job. `ST = CT − UT`
* **Requires Unscheduled Time to be calculated**
### Unscheduled Time
* Time the asset isn't assigned at all, because nothing requires it. 
* Planned shutdowns, holidays not worked, no work available, mobilisation and demobilisation, major rebuilds. 
* Condition of the machine is irrelevant here
* **Requires service hours in dataset**

### Available Time
* Required _and_ fit for duty. `AT = ST − DT`. About condition, not use — an idle but serviceable machine is still available.
* **Requires Scheduled time and Downtime to be calculated**

### Downtime
* The operation wants the asset but it isn't in a condition to perform its function.
* Left as one undivided bucket in the 2020 guideline; no industry consensus on splitting planned from unplanned maintenance, so that detail belongs in a CMMS.
* **Not derivable from datasets as need fault/maintenance log**

### Operating Time
* Available but not operating. `SB = SBO + SBE`
* **Operating standby (SBO)** — No immediate intent to run, for reasons within management control: no operator, shift change, crib breaks, meetings, training, no assignment issued.
* **External standby (SBE)** — Available, required and committed, but blocked by causes outside operating management's influence: client suspends work, work area closed by geotech or water, site-wide weather or power loss, workforce shortage. For a contractor this is the "off hours" state used for billing.
* `timestamp`, `timestampt_unix`, `position` to determine when away from from depot

### Standby
* Available and under the control of a human _or a system_. `OT = AT − SB`. 
* Conventionally gross operating hours (GOH).
* The "or system" wording is what makes the model work for autonomous fleets.
* `timestamp`, `timestamp_unix`, `position` Partially possible by investigating when stationary at depot during service hours
### Working Time
* Running but temporarily stopped by delays inherent to the operation or the immediate physical conditions.
* Within the operator's control conventionally, or the control system's control autonomously.
* Waiting for assignment, stuck, spill cleanup with operator aboard, loss of GPS or site wireless, safety stops.

### Operating Delay
* Operating as assigned and performing its intended function, covering activities that do and don't directly produce.
* `WT = OT − OD`
* Conventionally net operating hours (NOH)
* `timestamp`, `timestamp_unix`, `position`, partially possible - unplanned stops 

### Productive Time
* Unavoidable activity that doesn't directly produce but enables safe, efficient operation to continue. 
* Face cleanup, moving trailing cables, tramming, travel empty, waiting at the loading unit.
* `timestamp`, `timestamp_unix`, possible if \# of students in bus is counted

### Non-Productive Time
* Performing its intended function on activities that directly contribute to production. 
* `PT = WT − NP`
* If NP can't be isolated, fold the two together and report at working time.
* `timestamp`, `timestamp_unix`, possible if \# of students in bus is counted

## KPIs
* A measurable value showing how the business is performing on a key function.
#### Uptime
* `AT / CT`
* Time the asset was capable of operating, scheduled or not.
* Alternative offered in the guideline: calendar availability, `(CT − DT) / CT`, which strips effect of unscheduled time dragging down metric (often commercial decision over equipment problem)

#### Mechanical Availability
* `OT / (OT + DT)`
* The cleanest read on maintenance impact.
* Numerator is operating time, not available time, so standby is excluded and idle hours can't inflate it.
* Contrast physical availability, `AT / ST`, which does absorb standby.

#### Use of availability
* `OT / AT`
* How well the operation uses the equipment it has in working order.
* he maintenance-versus-operations dividing line: high mechanical availability with low use of availability means the fleet is fine and the operation isn't feeding it work.

#### Effective Utilisation
* `WT/ ST`
* Intended-function time against scheduled time.
* Clears downtime, standby and operating delay in one ratio, making it the closest single number to "did we get value from the shift".

#### Operating Efficiency
- `WT / OT`
- Delay burden once the machine is running.
- For an autonomous shuttle this is close to a direct readout of how often it stops for obstacles and pedestrians.

#### Physical Availability
* `AT / ST`

#### Asset Utilisation
* `OT / CT`

#### Operating Efficiency
* `WT / OT`

#### Production Effectiveness
* `PT / OT`


