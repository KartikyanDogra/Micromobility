# IIT Roorkee Micromobility Fleet Optimization

This work is done for a friend submitting a research proposal to IIT R for an e-mobility setup in the IIT Roorkee campus. 

## Project Overview

This repository contains an optimization framework for deploying a micromobility fleet, utilizing geographic data from a GeoJSON file to construct a realistic spatial network. It parses map features to categorize locations into production zones, such as residential hostels, and attraction zones, including academic departments and leisure areas. The underlying road network is extracted, simplified by merging nodes with degree-2 to reduce computational complexity, and connected to the zone centroids via calculated walking paths. After generating peak-hour travel demand (we did not have the actual demand data so, I considered a synthetic data) between the production and attraction zones, the code formulates a Mixed-Integer Non-Linear Programming model using Gurobi. The model aims to simultaneously optimize the placement of e-bike facilities, the required fleet size at each station, and a uniform distance-based fare to maximize overall system profit, factoring in fixed facility costs, variable bike deployment costs, and distance-based operational expenses.

## Mathematical Formulation

### Sets and Indices
*   $Z$: Set of all zones (production and attraction), indexed by $z$.
*   $S$: Set of all candidate station locations (intersections), indexed by $s$.
*   $N_z$: Subset of candidate stations within a reachable radius (0.25 km) of zone $z$.
*   $K$: Set of Origin-Destination (OD) pairs, indexed by $k = (o, d)$ where $o, d \in Z$.

### Parameters
*   $D_k$: Potential maximum demand for OD pair $k$.
*   $\delta_k$: Distance between the origin and destination of OD pair $k$ (km).
*   $P_{max}$: Maximum willingness to pay / maximum fare rate (Rs/km).
*   $V_{max}$: Maximum capacity of vehicles (bikes) allowed per facility.
*   $T$: Peak trips per vehicle (average trips one bike serves during the morning peak).
*   $FC$: Fixed cost to operate a facility (Rs/day).
*   $VC$: Variable cost per vehicle deployed at the facility (Rs/day).
*   $C_{op}$: Operational cost of a trip per km (Rs/km).

### Decision Variables
*   $y_s \in \{0, 1\}$: 1 if a facility is opened at candidate location $s$, 0 otherwise.
*   $x_{z,s} \in \{0, 1\}$: 1 if zone $z$ is assigned to facility $s$, 0 otherwise.
*   $v_s \in \mathbb{Z}^+$: Number of vehicles (bikes) stationed at facility $s$.
*   $p \ge 1.0$: Uniform fare charged per km.
*   $d_k \ge 0$: Actual demand served for OD pair $k$.
*   $w_{k,s} \ge 0$: Auxiliary variable linking the demand $d_k$ to the specific assigned origin station $s$.

### Objective Function
Maximize the total system profit, calculated as difference between the Revenue and running cost i.e. fixed Costs, variable fleet costs, and Operating Costs.

$$ \text{Maximize} \quad \sum_{k \in K} (p \cdot \delta_k \cdot d_k) - \sum_{s \in S} (FC \cdot y_s) - \sum_{s \in S} (VC \cdot v_s) - \sum_{k \in K} (C_{op} \cdot \delta_k \cdot d_k) $$

### Constraints

$$ \sum_{s \in N_z} x_{z,s} = 1 \quad \forall z \in Z \quad \quad (1)$$

$$ \sum_{s \in N_z} y_s \le 1 \quad \forall z \in Z \quad \quad (2)$$

$$ x_{z,s} \le y_s \quad \forall z \in Z, s \in N_z \quad \quad (3)$$

$$ d_k \le D_k \left( 1 - \frac{p}{P_{max}} \right) \quad \forall k \in K \quad \quad (4)$$

$$ \sum_{s \in N_o} w_{k,s} = d_k \quad \forall k=(o,d) \in K \quad \quad (5)$$

$$ w_{k,s} \le D_k \cdot x_{o,s} \quad \forall k=(o,d) \in K, s \in N_o \quad \quad (6)$$

$$ v_s \le V_{max} \cdot y_s \quad \forall s \in S \quad \quad (7)$$

$$ \sum_{k=(o,d) \in K \mid s \in N_o} w_{k,s} \le T \cdot v_s \quad \forall s \in S \quad \quad (8)$$

Constraint (1) guarantees full coverage by ensuring that every zone is assigned to exactly one facility within its reachable radius. Constraint (2) enforces exclusivity to prevent overlapping assignments; it dictates that at most one facility can be open among all the candidate stations available to any single zone. Constraint (3) ensures a valid facility assignment, establishing that a zone can only be assigned to a station if that station is actively open. Constraint (4) introduces demand elasticity, mathematically decreasing the actual demand as the fare increases, ultimately reaching zero if the fare hits a user's maximum willingness to pay. Constraints (5) and (6) link the served demand to specific stations; equation (5) ensures the total actual demand for an OD pair perfectly matches the sum of the demand assigned across reachable origin stations, while equation (6) dictates that demand can only originate from a station if the origin zone is officially assigned to it. Finally, Constraints (7) and (8) govern fleet sizing and capacity. Equation (7) ensures the number of vehicles at any location does not exceed the physical station capacity and that vehicles are only placed at opened stations. Equation (8) ensures that the total demand originating from a specific station does not exceed the transportation capacity of the vehicles stationed there during the peak period.

## Dependencies
* Python 3.x
* Gurobi Optimizer (gurobipy)
* NetworkX
* Matplotlib

## Execution
Just place a valid `map.geojson` file representing the area of interest in the working directory and run the script directly using Python:

```bash
python micromobility_model.py

