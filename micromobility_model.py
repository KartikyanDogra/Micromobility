import math
import json
import os
import matplotlib.pyplot as plt
import gurobipy as GRB
import networkx as nx
from gurobipy import Model, GRB

################################################################################################
# HELPER FUNCTIONS

def haversine(lon1, lat1, lon2, lat2):
    lon1, lat1, lon2, lat2 = map(math.radians,[lon1, lat1, lon2, lat2])
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a))
    r = 6371
    return c * r

def get_polygon_centroid(coords):
    ring = coords[0] 
    lon_sum = sum(pt[0] for pt in ring)
    lat_sum = sum(pt[1] for pt in ring)
    return lon_sum / len(ring), lat_sum / len(ring)

################################################################################################
# CLASSES

class Zone:
    def __init__(self, zone_id, lat, lon, name="", zone_type="attraction"):
        self.zone_id = zone_id
        self.lat = lat
        self.long = lon
        self.name = name
        self.zone_type = zone_type  # 'production' or 'attraction'
        self.dest = []
        self.origins =[]

class Node:
    def __init__(self, node_id, lat, lon):
        self.node_id = node_id
        self.lat = lat
        self.long = lon
        self.type = 'intersection'
        self.outLinks = []
        self.inLinks =[]

class Link:
    def __init__(self, from_node, to_node, dist, time, mode, geometry=None):
        self.fromNode = from_node
        self.toNode = to_node
        self.dist = round(dist, 4)
        self.time = round(time, 4)
        self.type = mode
        self.geometry = geometry if geometry else[]

class Demand:
    def __init__(self, from_zone, to_zone, demand_val):
        self.fromZone = from_zone
        self.toZone = to_zone
        self.demand = demand_val * 0.05
        self.pdemand = demand_val * 0.15

################################################################################################
# DATA STRUCTURES

zoneSet = {}
nodeSet = {}
linkSet = {}
tripSet = {}

def load_geojson_network(filepath, speed_walk_kmh=5.0, speed_ev_kmh=20.0):
    if not os.path.exists(filepath):
        print(f"Error: {filepath} not found!")
        return

    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    features = data.get('features',[])
    zone_count = 1

    prod_keywords =['bhawan', 'hostel', 'kunj', 'vihar', 'apartment', 'resid', 'azad wing']
    prod_tags = ['dormitory', 'residential', 'apartments']

    for feature in features:
        geom_type = feature['geometry']['type']
        coords = feature['geometry']['coordinates']
        props = feature.get('properties', {})

        is_building = props.get('building') is not None
        is_amenity = props.get('amenity') in ['university', 'department', 'college', 'library']
        is_leisure = props.get('leisure') in['pitch', 'stadium', 'sports_centre', 'park', 'track']

        if is_building or is_amenity or is_leisure:
            name_raw = str(props.get('name') or "")
            name_lower = name_raw.lower()
            building_tag = str(props.get('building') or "").lower()
            
            zone_type = "attraction" 
            if any(k in name_lower for k in prod_keywords) or building_tag in prod_tags:
                zone_type = "production"
            
            if geom_type == 'Polygon':
                lon, lat = get_polygon_centroid(coords)
            elif geom_type == 'Point':
                lon, lat = coords[0], coords[1]
            else: 
                continue 
            
            zone_id = f"Z_{zone_count}"
            zone_name = name_raw if name_raw else f"Unnamed_{zone_type.capitalize()}_{zone_count}"
            
            zoneSet[zone_id] = Zone(zone_id, lat, lon, zone_name, zone_type)
            zone_count += 1

        elif geom_type == 'LineString':
            def parse_osm_tags(tag_value):
                if not tag_value: return []
                if isinstance(tag_value, list):
                    return[str(v).lower().strip() for v in tag_value]
                val_str = str(tag_value).lower().strip()
                if val_str.startswith('[') and val_str.endswith(']'):
                    val_str = val_str[1:-1]
                    return[v.strip(" '\"") for v in val_str.split(',')]
                if ',' in val_str:
                    return[v.strip(" '\"") for v in val_str.split(',')]
                return [val_str]

            highway_vals = parse_osm_tags(props.get('highway'))
            surface_vals = parse_osm_tags(props.get('surface'))

            exclude_highways = {'footway', 'walkway', 'path', 'pedestrian'}
            exclude_surfaces = {'unpaved'}
            
            if any(h in exclude_highways for h in highway_vals) or any(s in exclude_surfaces for s in surface_vals):
                continue
            
            include_highways = {'residential', 'service', 'unclassified'}
            include_surfaces = {'paved', 'asphalt'}

            if any(h in include_highways for h in highway_vals) or any(s in include_surfaces for s in surface_vals):
                line_nodes =[]
                for pt in coords:
                    lon, lat = pt[0], pt[1]
                    node_id = f"{round(lon, 6)}_{round(lat, 6)}"
                    if node_id not in nodeSet:
                        nodeSet[node_id] = Node(node_id, lat, lon)
                    line_nodes.append(node_id)
                
                for i in range(len(line_nodes) - 1):
                    u, v = line_nodes[i], line_nodes[i+1]
                    if u == v: continue
                    
                    dist_km = haversine(nodeSet[u].long, nodeSet[u].lat, nodeSet[v].long, nodeSet[v].lat)
                    walk_time = (dist_km / speed_walk_kmh) * 60
                    ev_time = (dist_km / speed_ev_kmh) * 60
                    
                    geom = [(nodeSet[u].long, nodeSet[u].lat), (nodeSet[v].long, nodeSet[v].lat)]
                    rev_geom = [(nodeSet[v].long, nodeSet[v].lat), (nodeSet[u].long, nodeSet[u].lat)]
                    
                    linkSet[(u, v, 'walk')] = Link(u, v, dist_km, walk_time, 'walk', geom)
                    linkSet[(v, u, 'walk')] = Link(v, u, dist_km, walk_time, 'walk', rev_geom)
                    linkSet[(u, v, 'e-vehicle')] = Link(u, v, dist_km, ev_time, 'e-vehicle', geom)
                    linkSet[(v, u, 'e-vehicle')] = Link(v, u, dist_km, ev_time, 'e-vehicle', rev_geom)
                    
                    if v not in nodeSet[u].outLinks: nodeSet[u].outLinks.append(v)
                    if u not in nodeSet[v].inLinks: nodeSet[v].inLinks.append(u)
                    if u not in nodeSet[v].outLinks: nodeSet[v].outLinks.append(u)
                    if v not in nodeSet[u].inLinks: nodeSet[u].inLinks.append(v)

################################################################################################
# NETWORK SIMPLIFICATION & CONNECTING ZONES

def simplify_network():
    '''
    Merging the links with degree 2.
    '''
    global nodeSet, linkSet
    
    degree = {}
    for node_id, node in nodeSet.items():
        neighbors = set(node.outLinks + node.inLinks)
        degree[node_id] = len(neighbors)
        
    keep_nodes = set(n for n in nodeSet if degree[n] != 2)
    new_linkSet = {}
    visited_edges = set()
    modes =['walk', 'e-vehicle']
    
    for start_node in keep_nodes:
        neighbors = set(nodeSet[start_node].outLinks)
        for nxt in neighbors:
            edge_id = tuple(sorted([start_node, nxt]))
            if edge_id in visited_edges: continue
                
            path_nodes = [start_node, nxt]
            curr, prev = nxt, start_node
            
            while degree[curr] == 2 and curr not in keep_nodes:
                curr_neighbors = set(nodeSet[curr].outLinks + nodeSet[curr].inLinks)
                next_step = [x for x in curr_neighbors if x != prev][0]
                path_nodes.append(next_step)
                prev, curr = curr, next_step
                if curr == start_node: break
                    
            end_node = curr
            for i in range(len(path_nodes)-1):
                visited_edges.add(tuple(sorted([path_nodes[i], path_nodes[i+1]])))
                
            for mode in modes:
                total_dist, total_time = 0.0, 0.0
                geom =[]
                valid = True
                
                for i in range(len(path_nodes)-1):
                    u, v = path_nodes[i], path_nodes[i+1]
                    link_key = (u, v, mode)
                    if link_key in linkSet:
                        total_dist += linkSet[link_key].dist
                        total_time += linkSet[link_key].time
                        geom.append((nodeSet[u].long, nodeSet[u].lat))
                    else:
                        valid = False
                        break
                
                if valid:
                    geom.append((nodeSet[end_node].long, nodeSet[end_node].lat))
                    rev_geom = list(reversed(geom))
                    
                    new_linkSet[(start_node, end_node, mode)] = Link(start_node, end_node, total_dist, total_time, mode, geom)
                    new_linkSet[(end_node, start_node, mode)] = Link(end_node, start_node, total_dist, total_time, mode, rev_geom)

    nodeSet = {n: nodeSet[n] for n in keep_nodes}
    linkSet = new_linkSet
    
    for n in nodeSet.values():
        n.outLinks, n.inLinks = [],[]
        
    for (u, v, mode) in linkSet.keys():
        if v not in nodeSet[u].outLinks: nodeSet[u].outLinks.append(v)
        if u not in nodeSet[v].inLinks: nodeSet[v].inLinks.append(u)

def connect_zones_to_network(speed_walk_kmh=5.0):
    """
    Connecting zones to nearest network node i.e creating access/egress links
    """
    for z_id, zone in zoneSet.items():
        # Ensure zone centroid exists as a node to route from/to
        if z_id not in nodeSet:
            nodeSet[z_id] = Node(z_id, zone.lat, zone.long)
            nodeSet[z_id].type = 'zone'
        
        # Find the geometrically closest intersection node
        min_dist = float('inf')
        nearest_node = None
        
        for n_id, node in nodeSet.items():
            if node.type == 'intersection': 
                dist = haversine(zone.long, zone.lat, node.long, node.lat)
                if dist < min_dist:
                    min_dist = dist
                    nearest_node = n_id
                    
        # Create access/egress links
        if nearest_node:
            walk_time = (min_dist / speed_walk_kmh) * 60
            geom = [(zone.long, zone.lat), (nodeSet[nearest_node].long, nodeSet[nearest_node].lat)]
            rev_geom = [(nodeSet[nearest_node].long, nodeSet[nearest_node].lat), (zone.long, zone.lat)]
            
            linkSet[(z_id, nearest_node, 'walk_access')] = Link(z_id, nearest_node, min_dist, walk_time, 'walk_access', geom)
            linkSet[(nearest_node, z_id, 'walk_egress')] = Link(nearest_node, z_id, min_dist, walk_time, 'walk_egress', rev_geom)
            
            if nearest_node not in nodeSet[z_id].outLinks: nodeSet[z_id].outLinks.append(nearest_node)
            if z_id not in nodeSet[nearest_node].inLinks: nodeSet[nearest_node].inLinks.append(z_id)
            if z_id not in nodeSet[nearest_node].outLinks: nodeSet[nearest_node].outLinks.append(z_id)
            if nearest_node not in nodeSet[z_id].inLinks: nodeSet[z_id].inLinks.append(nearest_node)

################################################################################################
# DEMAND GENERATION

def generate_synthetic_demand(total_population=12000):
    global tripSet
    print(f"Generating synthetic demand for {total_population} residents...")
    
    prod_zones =[z for z in zoneSet.values() if z.zone_type == 'production']
    attr_zones = [z for z in zoneSet.values() if z.zone_type == 'attraction']
    
    if not prod_zones or not attr_zones:
        print("Warning: Missing production or attraction zones. Demand cannot be generated.")
        return
        
    # 12000 total / 10 Hostels = 1200 demand per hostel
    demand_per_prod = total_population / len(prod_zones)
    
    # 1200 demand per hostel / 36 Departments = 33.3 demand per OD pair
    demand_per_attr = demand_per_prod / len(attr_zones)
    
    for p in prod_zones:
        for a in attr_zones:
            pairId = (p.zone_id, a.zone_id)
            tripSet[pairId] = Demand(p.zone_id, a.zone_id, demand_per_attr)
            
            # Log origins and destinations inside the Zone objects
            if a.zone_id not in p.dest:
                p.dest.append(a.zone_id)
            if p.zone_id not in a.origins:
                a.origins.append(p.zone_id)

################################################################################################
# PRINTING & PLOTTING

def printNetworkStats():
    prod_count = sum(1 for z in zoneSet.values() if z.zone_type == 'production')
    attr_count = sum(1 for z in zoneSet.values() if z.zone_type == 'attraction')
    
    print("---------------------------------------------------------------------------------------------------")
    print(f"Total Zones:                 {len(zoneSet)}")
    print(f"  --> Production (Hostels):  {prod_count}")
    print(f"  --> Attraction (Depts):    {attr_count}")
    print(f"Total Nodes (Intersections): {sum(1 for n in nodeSet.values() if n.type == 'intersection')}")
    print(f"Total Links Created:         {len(linkSet)}")
    print(f"Total OD Pairs (Demand):     {len(tripSet)}")
    print("---------------------------------------------------------------------------------------------------")

def plotNetwork():
    print("Plotting the categorized network...")
    fig, ax = plt.subplots(figsize=(12, 10))
    
    # Plot Regular Network Links
    drawn_edges = set()
    for link_key, link_obj in linkSet.items():
        u, v, mode = link_key
        # Skip plotting zone access/egress links to keep map clean, or plot them as dotted lines
        if 'access' in mode or 'egress' in mode:
            lons = [pt[0] for pt in link_obj.geometry]
            lats =[pt[1] for pt in link_obj.geometry]
            ax.plot(lons, lats, color='black', linestyle=':', linewidth=1.5, zorder=1, alpha=0.5)
            continue
            
        edge_pair = tuple(sorted([u, v]))
        if edge_pair not in drawn_edges:
            lons = [pt[0] for pt in link_obj.geometry]
            lats = [pt[1] for pt in link_obj.geometry]
            ax.plot(lons, lats, color='#bdc3c7', linestyle='-', linewidth=2, zorder=1, alpha=0.6)
            drawn_edges.add(edge_pair)

    # Plot Nodes (Intersections)
    n_lons =[n.long for n in nodeSet.values() if n.type == 'intersection']
    n_lats =[n.lat for n in nodeSet.values() if n.type == 'intersection']
    ax.scatter(n_lons, n_lats, c='#7f8c8d', s=20, zorder=2, edgecolors='none', label='Intersections')

    # Plot Categories of Zones
    prod_lons =[z.long for z in zoneSet.values() if z.zone_type == 'production']
    prod_lats =[z.lat for z in zoneSet.values() if z.zone_type == 'production']
    
    attr_lons =[z.long for z in zoneSet.values() if z.zone_type == 'attraction']
    attr_lats =[z.lat for z in zoneSet.values() if z.zone_type == 'attraction']
    
    if prod_lons:
        ax.scatter(prod_lons, prod_lats, c='#2ecc71', s=120, zorder=3, edgecolors='black', 
                   marker='^', label='Production Zones (Hostels)')
                   
    if attr_lons:
        ax.scatter(attr_lons, attr_lats, c='#e74c3c', s=80, zorder=3, edgecolors='black', 
                   marker='s', label='Attraction Zones (Depts/Rec)')

    ax.set_aspect('equal')
    ax.set_title("IIT Roorkee: Trip Generation & Network Access", fontsize=16, fontweight='bold', pad=15)
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.grid(True, linestyle='--', alpha=0.4)
    ax.legend(loc="upper right", framealpha=0.9)
    
    plt.tight_layout()
    plt.show()


def optimize_facility_location(verbose=1):

    print("OPTIMIZING FACILITY LOCATION & MICROMOBILITY FLEET")

    
    # CANDIDATE LOCATIONS & REACHABILITY (0.25 km Buffer)
    BUFFER_RADIUS_KM = 0.25
    
    # Candidate facilities are all network intersections
    candidate_stations =[n_id for n_id, n in nodeSet.items() if n.type == 'intersection']
    
    N_z = {} # N_z[z] = list of candidate stations within 0.25km of zone z
    for z_id, z in zoneSet.items():
        reachable =[s for s in candidate_stations if haversine(z.long, z.lat, nodeSet[s].long, nodeSet[s].lat) <= BUFFER_RADIUS_KM]
        
        # Fallback: If 0.25km is too restrictive for a zone, find the closest possible intersection
        if not reachable:
            closest_s = min(candidate_stations, key=lambda s: haversine(z.long, z.lat, nodeSet[s].long, nodeSet[s].lat))
            reachable =[closest_s]
            print(f"Warning: Zone {z_id} has no intersections within {BUFFER_RADIUS_KM}km. Using closest ({haversine(z.long, z.lat, nodeSet[closest_s].long, nodeSet[closest_s].lat):.2f}km).")
            
        N_z[z_id] = reachable

    # ECONOMIC & OPERATIONAL PARAMETERS
    PEAK_TRIPS_PER_BIKE = 4.0      # Average trips one bike serves during morning peak
    MAX_FARE_RATE = 30.0           # Maximum Willingness to Pay (Rs per km)
    MAX_BIKES_PER_STATION = 50     # Facility capacity limit
    
    FC_STATION = 200.0             # Fixed Cost to operate a facility (Rs/day)
    VC_BIKE = 15.0                 # Variable Cost per bike deployed at the facility (Rs/day)
    C_OP_PER_KM = 0.50             # Operational cost of a trip per km (electricity/maintenance)

    m = Model("Facility_Location_Micromobility")
    m.Params.NonConvex = 2 
    m.Params.OutputFlag = verbose

    # y[s]: 1 if a facility is opened at candidate intersection s
    y = {s: m.addVar(vtype=GRB.BINARY, name=f"y_{s}") for s in candidate_stations}
    
    # x[z,s]: 1 if zone z is ASSIGNED to facility s
    x = {(z, s): m.addVar(vtype=GRB.BINARY, name=f"x_{z}_{s}") for z in zoneSet for s in N_z[z]}
    
    # bikes[s]: Number of bikes stationed at facility s
    bikes = {s: m.addVar(vtype=GRB.INTEGER, lb=0, ub=MAX_BIKES_PER_STATION, name=f"bikes_{s}") for s in candidate_stations}
    
    # p_dist: Uniform Fare charged per km
    p_dist = m.addVar(vtype=GRB.CONTINUOUS, lb=1.0, ub=MAX_FARE_RATE, name="fare_km")
    
    # d_vars[k]: Actual demand served for OD pair k
    d_vars = {k: m.addVar(vtype=GRB.CONTINUOUS, lb=0.0, ub=tripSet[k].demand, name=f"d_{k[0]}_{k[1]}") for k in tripSet}
    
    # w_vars[k,s]: Auxiliary variable to link demand to the specific assigned origin station
    w_vars = {(k, s): m.addVar(vtype=GRB.CONTINUOUS, lb=0.0, name=f"w_{k[0]}_{k[1]}_{s}") for k in tripSet for s in N_z[k[0]]}

    m.update()

    #  CONSTRAINTS

    # A. COVERAGE & FACILITY EXCLUSIVITY
    for z in zoneSet:
        # Every zone must be covered and assigned to exactly ONE facility
        m.addConstr(sum(x[z, s] for s in N_z[z]) == 1, name=f"Assign_{z}")
        
        # No two facilities are accessible from one demand zone
        # This mathematically forces that out of all candidate stations within 0.25km, AT MOST 1 can be open.
        m.addConstr(sum(y[s] for s in N_z[z]) <= 1, name=f"Exclusive_{z}")
        
        # A zone can only be assigned to a facility if that facility is OPEN
        for s in N_z[z]:
            m.addConstr(x[z, s] <= y[s], name=f"Link_x_y_{z}_{s}")

    # DEMAND & ELASTICITY
    for k in tripSet:
        o, dest = k
        pdemand = tripSet[k].demand
        
        # Elasticity (Higher fare = lower actual demand)
        m.addConstr(d_vars[k] <= pdemand * (1 - p_dist / MAX_FARE_RATE), name=f"Elast_{k}")
        
        # Link actual demand to the station assigned to the Origin
        m.addConstr(sum(w_vars[k, s] for s in N_z[o]) == d_vars[k], name=f"ConsW_{k}")
        for s in N_z[o]:
            # Demand can only originate at station 's' if origin 'o' is assigned to 's'
            m.addConstr(w_vars[k, s] <= pdemand * x[o, s], name=f"LinkW_{k}_{s}")

    # FLEET SIZING & CAPACITY
    for s in candidate_stations:
        # Cannot place bikes at a closed facility
        m.addConstr(bikes[s] <= MAX_BIKES_PER_STATION * y[s], name=f"MaxBikes_{s}")
        
        # The number of trips originating from this facility cannot exceed its Bike Capacity * Peak Trips per Bike
        orig_demand_s = sum(w_vars[k, s] for k in tripSet if s in N_z[k[0]])
        m.addConstr(orig_demand_s <= PEAK_TRIPS_PER_BIKE * bikes[s], name=f"BikeReq_{s}")

    #  OBJECTIVE: MAXIMIZE PROFIT
    trip_dist = {k: haversine(zoneSet[k[0]].long, zoneSet[k[0]].lat, zoneSet[k[1]].long, zoneSet[k[1]].lat) for k in tripSet}

    # Revenue = Price * Dist * Demand (Bilinear Non-Convex)
    revenue = sum(p_dist * trip_dist[k] * d_vars[k] for k in tripSet)
    
    fixed_costs = sum(FC_STATION * y[s] for s in candidate_stations)
    variable_facility_costs = sum(VC_BIKE * bikes[s] for s in candidate_stations)
    operating_costs = sum(C_OP_PER_KM * trip_dist[k] * d_vars[k] for k in tripSet)

    profit = revenue - fixed_costs - variable_facility_costs - operating_costs
    m.setObjective(profit, GRB.MAXIMIZE)
    m.optimize()

    if m.status == GRB.INFEASIBLE:
        m.computeIIS()
        m.write("model.ilp")
        print("Written conflict to model.ilp.")
        return None

    if m.status in[GRB.OPTIMAL, GRB.TIME_LIMIT]:
        opt_fare = p_dist.X
        total_fleet = sum(bikes[s].X for s in candidate_stations)
        num_stations = sum(y[s].X for s in candidate_stations)
        total_dem_served = sum(d_vars[k].X for k in tripSet)
        
        print("\n=== OPTIMIZATION RESULTS ===")
        print(f"Objective (Max Profit):  Rs {m.objVal:.2f}")
        print(f"Optimal Fare:            Rs {opt_fare:.2f} per km")
        print(f"Total Fleet Required:    {int(total_fleet)} e-bikes")
        print(f"Facilities Opened:       {int(num_stations)}")
        print(f"Total Trips Served:      {total_dem_served:.0f} peak trips")
        print("----------------------------")
        print(f"Revenue:                +Rs {revenue.getValue():.2f}")
        print(f"Facility Fixed Costs:   -Rs {fixed_costs.getValue():.2f}")
        print(f"Facility Var Costs:     -Rs {variable_facility_costs.getValue():.2f}")
        print(f"Trip Operating Costs:   -Rs {operating_costs.getValue():.2f}")
        print("============================\n")
        
        return {
            'profit': m.objVal,
            'fare_per_km': opt_fare,
            'fleet_size': int(total_fleet),
            'facilities': int(num_stations)
        }
    else:
        print("Optimization failed.")
        return None

################################################################################################
# MAIN EXECUTION

if __name__ == "__main__":
    geojson_file = 'Data/map.geojson' 
    
    load_geojson_network(geojson_file) 
    simplify_network()
    connect_zones_to_network() 
    generate_synthetic_demand(total_population=12000)
    optimize_facility_location(verbose=1)  # Set verbose=1 to see Gurobi logs
    # printNetworkStats()
    # plotNetwork()