"""
Central field registry for the property listing / submission phase.

This module is the single source of truth for which fields exist, which
property types / listing types they apply to, and how they should be
parsed and validated. It is used by:

  - routes/property_routes.py  (server-side parsing + validation)
  - templates/rentals.html     (dynamic form rendering + client-side JS,
                                 via `build_field_config()` serialized to JSON)

Keeping one registry means the frontend "show/hide" behaviour and the
backend "accept/reject" behaviour can never drift apart.
"""


# ============================================================
# PROPERTY TYPES
# ============================================================

PROPERTY_TYPES = [
    ("apartment", "Apartment / Flat"),
    ("independent_house", "Independent House"),
    ("villa", "Villa"),
    ("builder_floor", "Builder Floor"),
    ("plot", "Plot / Land"),
    ("farm_house", "Farm House"),
    ("pg_hostel", "PG / Hostel"),
    ("commercial", "Commercial Property"),
    ("other", "Other"),
]

PROPERTY_TYPE_VALUES = {value for value, _ in PROPERTY_TYPES}

LISTING_TYPES = [
    ("rent", "Rent"),
    ("sell", "Sell"),
]

LISTING_TYPE_VALUES = {value for value, _ in LISTING_TYPES}

# Property types that can only ever be rented (never sold).
RENT_ONLY_PROPERTY_TYPES = {"pg_hostel"}


# ============================================================
# OPTION LISTS
# ============================================================

FURNISHING_OPTIONS = [
    ("unfurnished", "Unfurnished"),
    ("semi_furnished", "Semi Furnished"),
    ("fully_furnished", "Fully Furnished"),
]

FACING_OPTIONS = [
    ("north", "North"),
    ("south", "South"),
    ("east", "East"),
    ("west", "West"),
    ("northeast", "North-East"),
    ("northwest", "North-West"),
    ("southeast", "South-East"),
    ("southwest", "South-West"),
]

WATER_SUPPLY_OPTIONS = [
    ("corporation", "Corporation"),
    ("borewell", "Borewell"),
    ("both", "Both"),
    ("tanker", "Tanker"),
]

POSSESSION_OPTIONS = [
    ("ready_to_move", "Ready to Move"),
    ("under_construction", "Under Construction"),
]

OWNERSHIP_OPTIONS = [
    ("freehold", "Freehold"),
    ("leasehold", "Leasehold"),
    ("cooperative_society", "Co-operative Society"),
    ("power_of_attorney", "Power of Attorney"),
]

LAND_USE_OPTIONS = [
    ("residential", "Residential"),
    ("commercial", "Commercial"),
    ("agricultural", "Agricultural"),
    ("mixed", "Mixed Use"),
]

TENANT_OPTIONS = [
    ("family", "Family"),
    ("bachelor", "Bachelor"),
    ("students", "Students"),
    ("working_professionals", "Working Professionals"),
    ("anyone", "Anyone"),
]

LEASE_TYPE_OPTIONS = [
    ("short_term", "Short Term"),
    ("long_term", "Long Term"),
]

TRANSACTION_TYPE_OPTIONS = [
    ("new", "New"),
    ("resale", "Resale"),
]

POSTED_BY_OPTIONS = [
    ("owner", "Owner"),
    ("agent", "Agent"),
    ("builder", "Builder / Developer"),
]

VILLA_TYPE_OPTIONS = [
    ("independent", "Independent Villa"),
    ("semi_detached", "Semi-detached"),
    ("row_villa", "Row Villa"),
    ("duplex", "Duplex"),
    ("triplex", "Triplex"),
]

OCCUPANCY_OPTIONS = [
    ("single", "Single"),
    ("double", "Double"),
    ("triple", "Triple"),
    ("multi", "Multi-sharing"),
]

GENDER_OPTIONS = [
    ("male", "Male"),
    ("female", "Female"),
    ("co_ed", "Co-ed / Any"),
]

TITLE_STATUS_OPTIONS = [
    ("clear", "Clear"),
    ("disputed", "Disputed"),
    ("under_verification", "Under Verification"),
]

APPROVAL_AUTHORITY_OPTIONS = [
    ("dtcp", "DTCP"),
    ("hmda", "HMDA / Local Development Authority"),
    ("panchayat", "Gram Panchayat"),
    ("municipal_corporation", "Municipal Corporation"),
    ("other", "Other"),
]

COMMERCIAL_TYPE_OPTIONS = [
    ("office_space", "Office Space"),
    ("shop", "Shop / Showroom"),
    ("warehouse", "Warehouse / Godown"),
    ("industrial_shed", "Industrial Shed"),
    ("other", "Other"),
]

BHK_OPTIONS = [
    ("1", "1 BHK"),
    ("1.5", "1.5 BHK"),
    ("2", "2 BHK"),
    ("2.5", "2.5 BHK"),
    ("3", "3 BHK"),
    ("3.5", "3.5 BHK"),
    ("4", "4 BHK"),
    ("5", "5+ BHK"),
]


ALL_PROPERTY_TYPES = PROPERTY_TYPE_VALUES


def _all_except(*excluded):
    return ALL_PROPERTY_TYPES - set(excluded)


# ============================================================
# FIELD GROUPS
#
# Every field dict may contain:
#   name        - form field name / document key            (required)
#   label       - human readable label                       (required)
#   kind        - str | text | int | float | bool | select | date
#   applies_to  - set of property_type values this field is relevant for
#   required    - whether it is mandatory for the applicable types
#   options     - list of (value, label) for kind == "select"
#   min / max   - numeric bounds
#   maxlen      - max string length
# ============================================================

COMMON_LISTING_FIELDS = [
    dict(name="title", label="Listing Title", kind="str",
         required=True, maxlen=120,
         applies_to=ALL_PROPERTY_TYPES),
    dict(name="description", label="Description", kind="text",
         maxlen=5000, applies_to=ALL_PROPERTY_TYPES),
    dict(name="price", label="Price", kind="float",
         required=True, min=1, applies_to=ALL_PROPERTY_TYPES),
    dict(name="price_negotiable", label="Price Negotiable", kind="bool",
         applies_to=ALL_PROPERTY_TYPES),
    dict(name="posted_by", label="Posted By", kind="select",
         options=POSTED_BY_OPTIONS, default="owner",
         applies_to=ALL_PROPERTY_TYPES),
]

LOCATION_FIELDS = [
    dict(name="address", label="Address", kind="str", required=True,
         applies_to=ALL_PROPERTY_TYPES),
    dict(name="state", label="State", kind="str",
         applies_to=ALL_PROPERTY_TYPES),
    dict(name="city", label="City", kind="str", required=True,
         applies_to=ALL_PROPERTY_TYPES),
    dict(name="locality", label="Locality", kind="str",
         applies_to=ALL_PROPERTY_TYPES),
    dict(name="sub_locality", label="Sub-locality", kind="str",
         applies_to=ALL_PROPERTY_TYPES),
    dict(name="landmark", label="Landmark", kind="str",
         applies_to=ALL_PROPERTY_TYPES),
    dict(name="pincode", label="Pincode", kind="pincode",
         applies_to=ALL_PROPERTY_TYPES),
]

ROOMS_FIELDS = [
    dict(name="bhk", label="BHK", kind="select", options=BHK_OPTIONS,
         required=True,
         applies_to={"apartment", "independent_house", "villa", "builder_floor"}),
    dict(name="bedrooms", label="Bedrooms", kind="int", min=0,
         applies_to={"farm_house"}, required=True),
    dict(name="bathrooms", label="Bathrooms", kind="int", min=0,
         applies_to=_all_except("plot", "pg_hostel")),
    dict(name="balconies", label="Balconies", kind="int", min=0,
         applies_to={"apartment", "independent_house", "villa", "builder_floor"}),
    dict(name="kitchens", label="Kitchens", kind="int", min=0,
         applies_to={"apartment", "independent_house", "villa", "builder_floor"}),
    dict(name="pooja_room", label="Pooja Room", kind="bool",
         applies_to={"independent_house", "villa", "builder_floor"}),
    dict(name="study_room", label="Study Room", kind="bool",
         applies_to={"independent_house", "villa"}),
    dict(name="servant_room", label="Servant Room", kind="bool",
         applies_to={"independent_house", "villa", "builder_floor"}),
    dict(name="store_room", label="Store Room", kind="bool",
         applies_to={"independent_house", "villa", "builder_floor"}),
    dict(name="utility_room", label="Utility Room", kind="bool",
         applies_to={"independent_house", "villa"}),
]

AREA_FIELDS = [
    dict(name="carpet_sqft", label="Carpet Area (sq.ft)", kind="float", min=1,
         applies_to={"apartment", "independent_house", "villa", "builder_floor", "commercial"}),
    dict(name="built_up_sqft", label="Built-up Area (sq.ft)", kind="float", min=1,
         required=True,
         applies_to={"apartment", "independent_house", "villa", "builder_floor", "commercial", "farm_house"}),
    dict(name="super_built_up_sqft", label="Super Built-up Area (sq.ft)", kind="float", min=1,
         applies_to={"apartment", "builder_floor", "commercial"}),
    dict(name="plot_sqft", label="Plot Area (sq.ft)", kind="float", min=1,
         required=True,
         applies_to={"independent_house", "villa", "plot", "farm_house"}),
    dict(name="length_ft", label="Plot Length (ft)", kind="float", min=1,
         applies_to={"plot", "independent_house"}),
    dict(name="width_ft", label="Plot Width (ft)", kind="float", min=1,
         applies_to={"plot", "independent_house"}),
    dict(name="frontage_ft", label="Frontage (ft)", kind="float", min=1,
         applies_to={"plot"}),
    dict(name="road_width_ft", label="Road Width (ft)", kind="float", min=1,
         applies_to={"plot"}),
]

BUILDING_FIELDS = [
    dict(name="floor_number", label="Floor", kind="int", min=0,
         applies_to={"apartment", "builder_floor"}, required=True),
    dict(name="total_floors", label="Total Floors", kind="int", min=1,
         applies_to={"apartment", "builder_floor", "villa"}, required=True),
    dict(name="number_of_floors", label="Number of Floors", kind="int", min=1,
         applies_to={"independent_house"}),
    dict(name="property_age", label="Property Age (years)", kind="int", min=0,
         applies_to=_all_except("plot", "pg_hostel")),
    dict(name="facing", label="Facing", kind="select", options=FACING_OPTIONS,
         applies_to=_all_except("pg_hostel")),
    dict(name="furnishing", label="Furnishing", kind="select", options=FURNISHING_OPTIONS,
         applies_to={"apartment", "independent_house", "villa", "builder_floor", "commercial"}),
    dict(name="flooring", label="Flooring", kind="str",
         applies_to={"apartment", "independent_house", "villa", "builder_floor"}),
    dict(name="lift", label="Lift", kind="bool",
         applies_to={"apartment", "builder_floor"}),
    dict(name="lift_count", label="Number of Lifts", kind="int", min=0,
         applies_to={"apartment"}),
    dict(name="power_backup", label="Power Backup", kind="bool",
         applies_to={"apartment", "independent_house", "villa", "builder_floor", "farm_house", "commercial"}),
    dict(name="water_supply", label="Water Supply", kind="select", options=WATER_SUPPLY_OPTIONS,
         applies_to={"apartment", "independent_house", "villa", "builder_floor", "farm_house"}),
    dict(name="gas_pipeline", label="Piped Gas", kind="bool",
         applies_to={"apartment", "independent_house", "villa", "builder_floor"}),
    dict(name="security", label="Security Personnel", kind="bool",
         applies_to={"apartment", "independent_house", "villa", "builder_floor", "commercial"}),
    dict(name="cctv", label="CCTV", kind="bool",
         applies_to={"apartment", "villa", "builder_floor", "commercial"}),
    dict(name="intercom", label="Intercom", kind="bool",
         applies_to={"apartment", "builder_floor"}),
    dict(name="maintenance_monthly", label="Monthly Maintenance", kind="float", min=0,
         applies_to={"apartment", "villa", "builder_floor", "commercial"}),
    dict(name="private_entrance", label="Private Entrance", kind="bool",
         applies_to={"independent_house", "builder_floor"}),
    dict(name="private_terrace", label="Private Terrace", kind="bool",
         applies_to={"independent_house", "villa", "builder_floor"}),
    dict(name="open_terrace", label="Open Terrace", kind="bool",
         applies_to={"independent_house"}),
    dict(name="roof_rights", label="Roof Rights", kind="bool",
         applies_to={"builder_floor"}),
    dict(name="garden", label="Garden", kind="bool",
         applies_to={"independent_house"}),
    dict(name="front_yard", label="Front Yard", kind="bool",
         applies_to={"independent_house"}),
    dict(name="backyard", label="Backyard", kind="bool",
         applies_to={"independent_house"}),
    dict(name="solar", label="Solar Power", kind="bool",
         applies_to={"independent_house", "farm_house", "villa"}),
    dict(name="generator_backup", label="Generator Backup", kind="bool",
         applies_to={"independent_house"}),
    dict(name="boundary_wall", label="Boundary Wall / Fencing", kind="bool",
         applies_to={"independent_house", "farm_house", "villa"}),
]

PROJECT_FIELDS = [
    dict(name="project_name", label="Project Name", kind="str",
         applies_to={"apartment", "villa", "builder_floor"}),
    dict(name="society_name", label="Society Name", kind="str",
         applies_to={"apartment", "independent_house", "villa", "builder_floor"}),
    dict(name="builder", label="Builder / Developer", kind="str",
         applies_to={"apartment", "villa", "builder_floor"}),
    dict(name="tower", label="Tower / Block", kind="str",
         applies_to={"apartment"}),
    dict(name="gated_community", label="Gated Community", kind="bool",
         applies_to={"apartment", "independent_house", "villa", "builder_floor"}),
    dict(name="clubhouse", label="Clubhouse", kind="bool",
         applies_to={"apartment", "villa"}),
    dict(name="common_pool", label="Common Swimming Pool", kind="bool",
         applies_to={"apartment", "villa"}),
]

# NOTE: possession_status / possession_date / rera_registered / rera_id
# intentionally live only in SALE_FIELDS (see below) — RERA disclosure
# and possession timelines are sale-transaction concepts in Indian real
# estate, and keeping a single source avoids the same field appearing
# twice (once from the project group, once from the sale group) for
# types like apartment/villa/builder_floor/plot when listing_type=sell.

PARKING_FIELDS = [
    dict(name="car_count", label="Car Parking", kind="int", min=0,
         applies_to=_all_except("plot", "pg_hostel", "farm_house")),
    dict(name="bike_count", label="Bike Parking", kind="int", min=0,
         applies_to=_all_except("plot", "pg_hostel", "farm_house")),
    dict(name="covered_parking", label="Covered Parking", kind="bool",
         applies_to=_all_except("plot", "pg_hostel", "farm_house")),
    dict(name="open_parking", label="Open Parking", kind="bool",
         applies_to=_all_except("plot", "pg_hostel", "farm_house")),
    dict(name="visitor_parking", label="Visitor Parking", kind="bool",
         applies_to={"apartment", "villa", "builder_floor", "commercial"}),
    dict(name="ev_charging", label="EV Charging", kind="bool",
         applies_to={"apartment", "villa", "builder_floor", "commercial"}),
    dict(name="dedicated_parking", label="Dedicated Parking", kind="bool",
         applies_to={"builder_floor"}),
]

# Property-type specific "extra" fields that don't fit the generic
# groups above (plot / villa / farmhouse / commercial specifics).
EXTRA_FIELDS = [
    # ---- Villa ----
    dict(name="villa_type", label="Villa Type", kind="select", options=VILLA_TYPE_OPTIONS,
         applies_to={"villa"}),
    dict(name="private_garden", label="Private Garden", kind="bool", applies_to={"villa"}),
    dict(name="private_pool", label="Private Swimming Pool", kind="bool", applies_to={"villa"}),
    dict(name="lawn", label="Lawn", kind="bool", applies_to={"villa"}),
    dict(name="home_theatre", label="Home Theatre", kind="bool", applies_to={"villa"}),
    dict(name="private_gym", label="Private Gym", kind="bool", applies_to={"villa"}),

    # ---- Plot / Land ----
    dict(name="open_sides", label="Number of Open Sides", kind="int", min=0, max=4,
         applies_to={"plot"}),
    dict(name="corner_plot", label="Corner Plot", kind="bool", applies_to={"plot"}),
    dict(name="boundary_wall_plot", label="Boundary Wall", kind="bool", applies_to={"plot"}),
    dict(name="gated_layout", label="Gated Layout", kind="bool", applies_to={"plot"}),
    dict(name="layout_name", label="Layout / Project Name", kind="str", applies_to={"plot"}),
    dict(name="plot_number", label="Plot Number", kind="str", applies_to={"plot"}),
    dict(name="block_sector", label="Block / Sector", kind="str", applies_to={"plot"}),
    dict(name="main_road_access", label="Main Road Access", kind="bool", applies_to={"plot"}),
    dict(name="land_use", label="Land Use", kind="select", options=LAND_USE_OPTIONS,
         applies_to={"plot"}, required=True),
    dict(name="zoning", label="Zoning", kind="str", applies_to={"plot"}),
    dict(name="approved_layout", label="Approved Layout", kind="bool", applies_to={"plot"}),
    dict(name="approval_authority", label="Approval Authority", kind="select",
         options=APPROVAL_AUTHORITY_OPTIONS, applies_to={"plot"}),
    dict(name="construction_allowed", label="Construction Allowed", kind="bool",
         applies_to={"plot"}),
    dict(name="max_floors_allowed", label="Maximum Floors Allowed", kind="int", min=0,
         applies_to={"plot"}),
    dict(name="electricity_available", label="Electricity Available", kind="bool",
         applies_to={"plot"}),
    dict(name="water_available", label="Water Available", kind="bool", applies_to={"plot"}),
    dict(name="borewell", label="Borewell", kind="bool", applies_to={"plot", "farm_house"}),
    dict(name="drainage", label="Drainage", kind="bool", applies_to={"plot"}),
    dict(name="sewage", label="Sewage Connection", kind="bool", applies_to={"plot"}),
    dict(name="gas_available", label="Gas Available", kind="bool", applies_to={"plot"}),
    dict(name="internet_available", label="Internet Available", kind="bool", applies_to={"plot"}),

    # ---- Farm House ----
    dict(name="farmhouse_garden", label="Garden", kind="bool", applies_to={"farm_house"}),
    dict(name="orchard", label="Orchard", kind="bool", applies_to={"farm_house"}),
    dict(name="swimming_pool", label="Swimming Pool", kind="bool", applies_to={"farm_house"}),
    dict(name="water_source", label="Water Source", kind="select", options=WATER_SUPPLY_OPTIONS,
         applies_to={"farm_house"}),
    dict(name="farm_road_access", label="Farm Road Access", kind="bool", applies_to={"farm_house"}),
    dict(name="servant_quarters", label="Servant Quarters", kind="bool", applies_to={"farm_house"}),
    dict(name="storage", label="Storage", kind="bool", applies_to={"farm_house"}),
    dict(name="agricultural_land", label="Agricultural Land", kind="bool", applies_to={"farm_house"}),
    dict(name="livestock_area", label="Animal / Livestock Area", kind="bool", applies_to={"farm_house"}),
    dict(name="main_road_distance_km", label="Distance from Main Road (km)", kind="float", min=0,
         applies_to={"farm_house"}),
    dict(name="land_use_farmhouse", label="Land Use", kind="select", options=LAND_USE_OPTIONS,
         applies_to={"farm_house"}),

    # ---- Commercial ----
    dict(name="commercial_type", label="Commercial Type", kind="select",
         options=COMMERCIAL_TYPE_OPTIONS, applies_to={"commercial"}, required=True),
    dict(name="washrooms", label="Washrooms", kind="int", min=0, applies_to={"commercial"}),
    dict(name="cabins", label="Cabins", kind="int", min=0, applies_to={"commercial"}),
    dict(name="conference_room", label="Conference Room", kind="bool", applies_to={"commercial"}),
    dict(name="reception_area", label="Reception Area", kind="bool", applies_to={"commercial"}),
    dict(name="pantry", label="Pantry", kind="bool", applies_to={"commercial"}),
    dict(name="power_load_kva", label="Power Load (KVA)", kind="float", min=0,
         applies_to={"commercial"}),
    dict(name="fire_noc", label="Fire NOC", kind="bool", applies_to={"commercial"}),

    # ---- Other ----
    dict(name="other_notes", label="Additional Notes", kind="text", applies_to={"other"}),
]

LEGAL_FIELDS = [
    dict(name="ownership_type", label="Ownership Type", kind="select", options=OWNERSHIP_OPTIONS,
         applies_to={"apartment", "independent_house", "villa", "builder_floor",
                     "plot", "farm_house", "commercial"}),
    dict(name="title_status", label="Title Status", kind="select", options=TITLE_STATUS_OPTIONS,
         applies_to={"plot"}),
    dict(name="encumbrance_status", label="Encumbrance Status", kind="select",
         options=[("clear", "Clear"), ("encumbered", "Encumbered")],
         applies_to={"plot"}),
]

# NOTE: existing_loan / loan_outstanding intentionally live only in
# SALE_FIELDS — loan disclosure is a buyer-facing (sale) concern, so it
# is not duplicated here.

# ---- PG / Hostel (entirely separate structure) ----
PG_FIELDS = [
    dict(name="occupancy_type", label="Occupancy Type", kind="select", options=OCCUPANCY_OPTIONS,
         applies_to={"pg_hostel"}, required=True),
    dict(name="gender_preference", label="Gender Preference", kind="select", options=GENDER_OPTIONS,
         applies_to={"pg_hostel"}, required=True),
    dict(name="food_available", label="Food Available", kind="bool", applies_to={"pg_hostel"}),
    dict(name="food_included", label="Food Included in Rent", kind="bool", applies_to={"pg_hostel"}),
    dict(name="ac", label="AC Room", kind="bool", applies_to={"pg_hostel"}),
    dict(name="attached_bathroom", label="Attached Bathroom", kind="bool", applies_to={"pg_hostel"}),
    dict(name="wifi", label="Wi-Fi", kind="bool", applies_to={"pg_hostel"}),
    dict(name="laundry", label="Laundry", kind="bool", applies_to={"pg_hostel"}),
    dict(name="housekeeping", label="Housekeeping", kind="bool", applies_to={"pg_hostel"}),
    dict(name="security_pg", label="Security", kind="bool", applies_to={"pg_hostel"}),
    dict(name="curfew", label="Curfew Timing", kind="str", applies_to={"pg_hostel"}),
    dict(name="deposit", label="Security Deposit", kind="float", min=0,
         applies_to={"pg_hostel"}, required=True),
    dict(name="electricity_charges_extra", label="Electricity Charges Extra", kind="bool",
         applies_to={"pg_hostel"}),
    dict(name="available_from_pg", label="Available From", kind="date", applies_to={"pg_hostel"}),
    dict(name="notice_period_days_pg", label="Notice Period (days)", kind="int", min=0,
         applies_to={"pg_hostel"}),
    dict(name="lock_in_months_pg", label="Lock-in Period (months)", kind="int", min=0,
         applies_to={"pg_hostel"}),
    dict(name="parking_pg", label="Parking Available", kind="bool", applies_to={"pg_hostel"}),
    dict(name="common_areas", label="Common Areas", kind="bool", applies_to={"pg_hostel"}),
]

RENT_FIELDS = [
    dict(name="security_deposit", label="Security Deposit", kind="float", min=0),
    dict(name="maintenance_charge", label="Monthly Maintenance", kind="float", min=0),
    dict(name="maintenance_included", label="Maintenance Included in Rent", kind="bool"),
    dict(name="available_from", label="Available From", kind="date"),
    dict(name="preferred_tenant", label="Preferred Tenant", kind="select", options=TENANT_OPTIONS),
    dict(name="pets_allowed", label="Pets Allowed", kind="tribool"),
    dict(name="smoking_allowed", label="Smoking Allowed", kind="tribool"),
    dict(name="non_veg_allowed", label="Non-Veg Allowed", kind="tribool"),
    dict(name="lease_type", label="Lease Type", kind="select", options=LEASE_TYPE_OPTIONS),
    dict(name="lease_duration_months", label="Lease Duration (months)", kind="int", min=0),
    dict(name="lock_in_months", label="Lock-in Period (months)", kind="int", min=0),
    dict(name="notice_period_days", label="Notice Period (days)", kind="int", min=0),
    dict(name="rent_escalation_percent", label="Annual Rent Escalation (%)", kind="float", min=0, max=100),
    dict(name="brokerage", label="Brokerage Applicable", kind="bool"),
    dict(name="brokerage_amount", label="Brokerage Amount", kind="float", min=0),
    dict(name="electricity_charges", label="Electricity Charges", kind="str"),
    dict(name="water_charges", label="Water Charges", kind="str"),
    dict(name="other_charges", label="Other Recurring Charges", kind="str"),
    dict(name="max_occupants", label="Maximum Occupants", kind="int", min=1),
]

SALE_FIELDS = [
    dict(name="price_per_sqft", label="Price per sq.ft", kind="float", min=0),
    dict(name="booking_amount", label="Booking Amount", kind="float", min=0),
    dict(name="maintenance", label="Maintenance", kind="float", min=0),
    dict(name="maintenance_frequency", label="Maintenance Frequency", kind="select",
         options=[("monthly", "Monthly"), ("quarterly", "Quarterly"), ("annually", "Annually")]),
    dict(name="transaction_type", label="Transaction Type", kind="select",
         options=TRANSACTION_TYPE_OPTIONS),
    dict(name="possession_status", label="Possession Status", kind="select",
         options=POSSESSION_OPTIONS),
    dict(name="possession_date", label="Possession Date", kind="date"),
    dict(name="existing_loan", label="Existing Loan", kind="bool"),
    dict(name="loan_outstanding", label="Loan Outstanding Amount", kind="float", min=0),
    dict(name="rera_registered", label="RERA Registered", kind="bool"),
    dict(name="rera_id", label="RERA ID", kind="str"),
    dict(name="brokerage", label="Brokerage Applicable", kind="bool"),
    dict(name="brokerage_amount", label="Brokerage Amount", kind="float", min=0),
]


# ============================================================
# AMENITIES (categorized, multi-select)
# ============================================================

AMENITY_CATEGORIES = {
    "building": [
        ("lift", "Lift"),
        ("power_backup", "Power Backup"),
        ("security", "24x7 Security"),
        ("cctv", "CCTV Surveillance"),
        ("intercom", "Intercom"),
        ("fire_safety", "Fire Safety"),
        ("water_supply", "24x7 Water Supply"),
        ("gas_pipeline", "Piped Gas"),
        ("solar", "Solar Power"),
        ("ev_charging", "EV Charging"),
    ],
    "recreation": [
        ("swimming_pool", "Swimming Pool"),
        ("gym", "Gymnasium"),
        ("clubhouse", "Clubhouse"),
        ("indoor_games", "Indoor Games"),
        ("outdoor_games", "Outdoor Games"),
        ("childrens_play_area", "Children's Play Area"),
        ("jogging_track", "Jogging Track"),
        ("sports_facilities", "Sports Facilities"),
    ],
    "outdoor": [
        ("garden", "Garden"),
        ("park", "Park"),
        ("lawn", "Lawn"),
        ("terrace_garden", "Terrace Garden"),
    ],
    "property": [
        ("modular_kitchen", "Modular Kitchen"),
        ("pooja_room", "Pooja Room"),
        ("study_room", "Study Room"),
        ("store_room", "Store Room"),
        ("utility_room", "Utility Room"),
        ("servant_room", "Servant Room"),
        ("balcony", "Balcony"),
        ("private_terrace", "Private Terrace"),
        ("home_theatre", "Home Theatre"),
    ],
    "parking": [
        ("covered_parking", "Covered Parking"),
        ("open_parking", "Open Parking"),
        ("visitor_parking", "Visitor Parking"),
        ("ev_charging_parking", "EV Charging"),
    ],
}


# ============================================================
# GROUP DEFINITIONS
# ============================================================

# (group key, field list, group applies globally or per-field via applies_to)
FIELD_GROUPS = [
    ("rooms", ROOMS_FIELDS),
    ("area", AREA_FIELDS),
    ("building", BUILDING_FIELDS),
    ("project", PROJECT_FIELDS),
    ("parking", PARKING_FIELDS),
    ("extra", EXTRA_FIELDS),
    ("legal", LEGAL_FIELDS),
    ("pg", PG_FIELDS),
]


def fields_for_type(group_fields, property_type):
    """Return the subset of a field list that applies to a property type."""

    return [
        field
        for field in group_fields
        if property_type in field.get("applies_to", ALL_PROPERTY_TYPES)
    ]


def build_field_config():
    """
    Serialize the registry into a plain-data structure safe for
    `tojson` embedding in the listing submission template, so the
    frontend's dynamic show/hide logic is driven by the same source
    of truth as backend validation.
    """

    def strip_sets(fields):
        cleaned = []

        for field in fields:
            entry = dict(field)
            entry["applies_to"] = sorted(entry.get("applies_to", ALL_PROPERTY_TYPES))
            cleaned.append(entry)

        return cleaned

    return {
        "propertyTypes": PROPERTY_TYPES,
        "listingTypes": LISTING_TYPES,
        "rentOnlyPropertyTypes": sorted(RENT_ONLY_PROPERTY_TYPES),
        "commonListingFields": strip_sets(COMMON_LISTING_FIELDS),
        "locationFields": strip_sets(LOCATION_FIELDS),
        "groups": {
            key: strip_sets(fields)
            for key, fields in FIELD_GROUPS
        },
        "rentFields": strip_sets(RENT_FIELDS),
        "saleFields": strip_sets(SALE_FIELDS),
        "amenityCategories": AMENITY_CATEGORIES,
    }


def build_label_lookup():
    """
    Flatten every field's `name -> label` across all groups, for use
    by the (read-only) property detail / profile pages so they can
    show a human label for any key found in a stored document without
    hand-writing a parallel set of labels there.
    """

    lookup = {}

    all_field_lists = [
        COMMON_LISTING_FIELDS,
        LOCATION_FIELDS,
        ROOMS_FIELDS,
        AREA_FIELDS,
        BUILDING_FIELDS,
        PROJECT_FIELDS,
        PARKING_FIELDS,
        EXTRA_FIELDS,
        LEGAL_FIELDS,
        PG_FIELDS,
        RENT_FIELDS,
        SALE_FIELDS,
    ]

    for field_list in all_field_lists:
        for field in field_list:
            lookup.setdefault(field["name"], field["label"])

    return lookup


def build_amenity_label_lookup():
    """Flatten `amenity code -> label` across every category."""

    lookup = {}

    for options in AMENITY_CATEGORIES.values():
        for value, label in options:
            lookup[value] = label

    return lookup
