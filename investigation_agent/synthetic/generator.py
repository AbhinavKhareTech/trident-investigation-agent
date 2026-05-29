"""Synthetic data generator with embedded anomaly patterns.

Generates realistic CSVs that the investigation agent can ingest.
Patterns are deterministic so the demo is reproducible.

Default domain: Insurance claims (most visual).
But the generator is parameterized — swap entity_types for AML, vendor risk, etc.
"""

from __future__ import annotations

import csv
import json
import os
import random
from datetime import datetime, timedelta
from pathlib import Path

# Deterministic for reproducible demos
random.seed(42)

# ─── Indian-context names and locations ───

FIRST_NAMES = [
    "Rahul", "Priya", "Amit", "Sneha", "Vikram", "Ananya", "Suresh", "Kavitha",
    "Rajesh", "Deepa", "Arjun", "Lakshmi", "Venkat", "Meera", "Sanjay", "Nisha",
    "Kiran", "Swathi", "Manoj", "Divya", "Ramesh", "Pooja", "Arun", "Asha",
    "Harish", "Ritu", "Ganesh", "Sunita", "Nikhil", "Bhavya",
]

LAST_NAMES = [
    "Sharma", "Patel", "Reddy", "Kumar", "Nair", "Iyer", "Gupta", "Singh",
    "Rao", "Das", "Joshi", "Menon", "Verma", "Pillai", "Agarwal", "Bhat",
    "Shetty", "Mishra", "Hegde", "Kulkarni", "Desai", "Patil", "Choudhury",
    "Banerjee", "Mukherjee", "Saxena", "Kaur", "Malhotra", "Dutta", "Thakur",
]

CITIES = [
    "Bangalore", "Mumbai", "Delhi", "Chennai", "Hyderabad",
    "Pune", "Kolkata", "Ahmedabad", "Kochi", "Jaipur",
]

AREAS = {
    "Bangalore": ["Koramangala", "Indiranagar", "HSR Layout", "Whitefield", "Jayanagar", "JP Nagar", "Marathahalli", "Electronic City"],
    "Mumbai": ["Andheri", "Bandra", "Powai", "Dadar", "Malad", "Goregaon", "Juhu", "Thane"],
    "Delhi": ["Connaught Place", "Karol Bagh", "Dwarka", "Rohini", "Lajpat Nagar", "Saket"],
    "Chennai": ["T Nagar", "Adyar", "Anna Nagar", "Velachery", "Mylapore", "Guindy"],
    "Hyderabad": ["Banjara Hills", "Gachibowli", "Madhapur", "Kukatpally", "Jubilee Hills"],
}

GARAGES = [
    "QuickFix Auto", "Speedy Repairs", "Metro Body Shop", "Elite Auto Care",
    "RoadKing Garage", "Krishna Motors", "Sunrise Auto Works", "Victory Repairs",
    "City Auto Hub", "Premium Care Workshop", "Jai Hind Motors", "Star Body Shop",
]

HOSPITALS = [
    "City General Hospital", "Apollo Clinic", "Fortis Health", "Max Care Hospital",
    "Medanta", "Narayana Health", "Columbia Asia", "Manipal Hospital",
]

AGENTS = [
    "AG-Mohit", "AG-Priya", "AG-Sanjay", "AG-Deepa", "AG-Rakesh",
    "AG-Anita", "AG-Varun", "AG-Swati", "AG-Ajay", "AG-Neha",
]

PHONE_PREFIXES = ["98", "97", "96", "95", "88", "87", "86", "70", "99", "91"]

VEHICLE_MAKES = [
    ("Maruti", ["Swift", "Dzire", "Baleno", "WagonR", "Alto", "Ertiga"]),
    ("Hyundai", ["i20", "Creta", "Verna", "Venue", "i10"]),
    ("Tata", ["Nexon", "Punch", "Harrier", "Altroz", "Safari"]),
    ("Honda", ["City", "Amaze", "Jazz", "WRV"]),
    ("Toyota", ["Fortuner", "Innova", "Glanza", "Urban Cruiser"]),
    ("Mahindra", ["XUV700", "Thar", "Scorpio", "XUV300"]),
]

DAMAGE_TYPES = [
    "Front bumper", "Rear bumper", "Side panel", "Windshield",
    "Headlights", "Fender", "Hood", "Door panel", "Roof",
]

CLAIM_DESCRIPTIONS = [
    "Rear-ended at traffic signal",
    "Side collision at intersection",
    "Hit by unidentified vehicle while parked",
    "Collision during lane change on highway",
    "Damage from road debris",
    "Multi-vehicle pile-up on flyover",
    "Vehicle hit by auto-rickshaw",
    "Collision with two-wheeler",
    "Damage during flooding",
    "Hit-and-run on service road",
]


def _random_phone() -> str:
    prefix = random.choice(PHONE_PREFIXES)
    return f"+91{prefix}{random.randint(10000000, 99999999)}"


def _random_vehicle() -> tuple[str, str, int]:
    make, models = random.choice(VEHICLE_MAKES)
    model = random.choice(models)
    year = random.randint(2017, 2025)
    return make, model, year


def _random_amount(low: int, high: int) -> int:
    return round(random.randint(low, high) / 100) * 100


def _random_date(days_back: int = 180) -> str:
    d = datetime.now() - timedelta(days=random.randint(1, days_back))
    return d.strftime("%Y-%m-%d")


def generate_dataset(
    output_dir: str = "./incoming_data",
    n_normal: int = 200,
    n_fraud_ring: int = 1,
    ring_size: int = 8,
) -> dict[str, str]:
    """Generate a complete CSV dataset with embedded fraud patterns.

    Returns dict of {filename: filepath} for all generated files.
    """
    os.makedirs(output_dir, exist_ok=True)

    customers: list[dict] = []
    claims: list[dict] = []
    payments: list[dict] = []
    agents_list: list[dict] = []

    customer_id_counter = 1000
    claim_id_counter = 5000

    # ─── Agents ───
    for ag in AGENTS:
        agents_list.append({
            "agent_id": ag,
            "name": ag.replace("AG-", ""),
            "region": random.choice(CITIES),
            "active_since": _random_date(days_back=1000),
            "cases_handled": random.randint(50, 500),
        })

    # ─── Normal claims ───
    used_phones: set[str] = set()
    for _ in range(n_normal):
        customer_id_counter += 1
        cid = f"CUS-{customer_id_counter}"
        city = random.choice(CITIES)
        area = random.choice(AREAS.get(city, ["Central"]))
        phone = _random_phone()
        used_phones.add(phone)

        customers.append({
            "customer_id": cid,
            "name": f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}",
            "phone": phone,
            "email": f"cust{customer_id_counter}@email.com",
            "city": city,
            "area": area,
            "address": f"{random.randint(1,999)}, {area}, {city}",
            "risk_tier": random.choice(["low", "low", "low", "medium", "medium", "high"]),
        })

        make, model, year = _random_vehicle()
        claim_id_counter += 1

        repair_amount = _random_amount(5000, 120000)
        medical_amount = _random_amount(0, 30000) if random.random() < 0.3 else 0

        claims.append({
            "claim_id": f"CLM-{claim_id_counter}",
            "customer_id": cid,
            "date": _random_date(),
            "vehicle": f"{make} {model} {year}",
            "damage": random.choice(DAMAGE_TYPES),
            "description": random.choice(CLAIM_DESCRIPTIONS),
            "repair_amount": repair_amount,
            "medical_amount": medical_amount,
            "total_amount": repair_amount + medical_amount,
            "garage": random.choice(GARAGES),
            "hospital": random.choice(HOSPITALS) if medical_amount > 0 else "",
            "agent_id": random.choice(AGENTS),
            "status": random.choice(["approved", "approved", "approved", "under_review", "settled"]),
            "city": city,
        })

        if claims[-1]["status"] in ("approved", "settled"):
            payments.append({
                "payment_id": f"PAY-{claim_id_counter}",
                "claim_id": f"CLM-{claim_id_counter}",
                "customer_id": cid,
                "amount": repair_amount + medical_amount,
                "date": _random_date(days_back=90),
                "payee": claims[-1]["garage"],
                "method": random.choice(["NEFT", "RTGS", "cheque", "UPI"]),
            })

    # ─── Fraud rings ───
    for ring_idx in range(n_fraud_ring):
        # The ring shares: one garage, one hospital, and 2-3 phone numbers
        ring_garage = f"RapidFix Auto Hub"  # Distinctive name
        ring_hospital = "MedCare Wellness Clinic"
        ring_agent = random.choice(AGENTS[:3])  # Same agent handles all
        ring_city = "Bangalore"
        ring_area = "Koramangala"

        # Shared identifiers (the smoking gun)
        shared_phones = [_random_phone() for _ in range(2)]
        shared_address = f"42, 3rd Cross, {ring_area}, {ring_city}"

        # Burst timing (all claims within 5 days)
        base_date = datetime.now() - timedelta(days=random.randint(10, 30))

        for i in range(ring_size):
            customer_id_counter += 1
            cid = f"CUS-{customer_id_counter}"

            # Some customers share phone/address (the red flag)
            if i < 3:
                phone = shared_phones[0]
                address = shared_address
            elif i < 5:
                phone = shared_phones[1]
                address = shared_address
            else:
                phone = _random_phone()
                address = f"{random.randint(1,99)}, {ring_area}, {ring_city}"

            customers.append({
                "customer_id": cid,
                "name": f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}",
                "phone": phone,
                "email": f"ring{ring_idx}_{i}@email.com",
                "city": ring_city,
                "area": ring_area,
                "address": address,
                "risk_tier": "low",  # Appear low-risk individually
            })

            make, model, year = _random_vehicle()
            claim_id_counter += 1
            claim_date = (base_date + timedelta(days=random.randint(0, 4))).strftime("%Y-%m-%d")

            # Inflated amounts (another signal)
            repair_amount = _random_amount(65000, 180000)
            medical_amount = _random_amount(15000, 45000)

            claims.append({
                "claim_id": f"CLM-{claim_id_counter}",
                "customer_id": cid,
                "date": claim_date,
                "vehicle": f"{make} {model} {year}",
                "damage": random.choice(DAMAGE_TYPES[:3]),  # Limited damage types
                "description": "Multi-vehicle collision at junction",
                "repair_amount": repair_amount,
                "medical_amount": medical_amount,
                "total_amount": repair_amount + medical_amount,
                "garage": ring_garage,
                "hospital": ring_hospital,
                "agent_id": ring_agent,
                "status": "approved",
                "city": ring_city,
            })

            payments.append({
                "payment_id": f"PAY-{claim_id_counter}",
                "claim_id": f"CLM-{claim_id_counter}",
                "customer_id": cid,
                "amount": repair_amount + medical_amount,
                "date": claim_date,
                "payee": ring_garage,
                "method": "NEFT",
            })

    # ─── Write CSVs ───
    files = {}
    for filename, data in [
        ("customers.csv", customers),
        ("claims.csv", claims),
        ("payments.csv", payments),
        ("agents.csv", agents_list),
    ]:
        filepath = os.path.join(output_dir, filename)
        if data:
            with open(filepath, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=data[0].keys())
                writer.writeheader()
                writer.writerows(data)
            files[filename] = filepath

    # ─── Write manifest ───
    manifest = {
        "generated_at": datetime.now().isoformat(),
        "counts": {
            "customers": len(customers),
            "claims": len(claims),
            "payments": len(payments),
            "agents": len(agents_list),
        },
        "embedded_patterns": {
            "fraud_rings": n_fraud_ring,
            "ring_size": ring_size,
            "signals": [
                "shared_phone_numbers",
                "shared_address",
                "same_garage_cluster",
                "same_hospital_cluster",
                "temporal_burst",
                "inflated_amounts",
                "same_agent",
            ],
        },
    }
    manifest_path = os.path.join(output_dir, "manifest.json")
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
    files["manifest.json"] = manifest_path

    return files


if __name__ == "__main__":
    files = generate_dataset()
    for name, path in files.items():
        print(f"  {name}: {path}")
