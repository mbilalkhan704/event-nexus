from config import get_driver, run

STATEMENTS = [
    "CREATE CONSTRAINT event_id IF NOT EXISTS FOR (n:Event) REQUIRE n.eventid IS UNIQUE",
    "CREATE CONSTRAINT group_name IF NOT EXISTS FOR (n:Group) REQUIRE n.name IS UNIQUE",
    "CREATE CONSTRAINT attacktype_name IF NOT EXISTS FOR (n:AttackType) REQUIRE n.name IS UNIQUE",
    "CREATE CONSTRAINT weapontype_name IF NOT EXISTS FOR (n:WeaponType) REQUIRE n.name IS UNIQUE",
    "CREATE CONSTRAINT targettype_name IF NOT EXISTS FOR (n:TargetType) REQUIRE n.name IS UNIQUE",
    "CREATE CONSTRAINT targetorg_name IF NOT EXISTS FOR (n:TargetOrg) REQUIRE n.name IS UNIQUE",
    "CREATE CONSTRAINT source_citation IF NOT EXISTS FOR (n:Source) REQUIRE n.citation IS UNIQUE",
    "CREATE CONSTRAINT area_name IF NOT EXISTS FOR (n:Area) REQUIRE n.name IS UNIQUE",
    "CREATE INDEX event_date IF NOT EXISTS FOR (n:Event) ON (n.date)",
    "CREATE CONSTRAINT locality_name IF NOT EXISTS FOR (n:Locality) REQUIRE n.name IS UNIQUE",
]

driver = get_driver()
for statement in STATEMENTS:
    run(driver, statement)
    print("OK:", statement[:70])

print("\nConstraints:", len(run(driver, "SHOW CONSTRAINTS")))
print("Indexes:", len(run(driver, "SHOW INDEXES")))
print("Nodes in database:", run(driver, "MATCH (n) RETURN count(n) AS c")[0]["c"])
driver.close()
