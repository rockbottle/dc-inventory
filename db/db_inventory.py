from sqlalchemy.orm.session import Session
from sqlalchemy import and_, func
from schemas import DcInvBase, DcInvUpdate
from db.models import DcInventory, DcUser, DcPurchase
from fastapi import HTTPException, status

# --- CAPACITY FACT-CHECKER (THE GATEKEEPER) ---

def check_company_capacity(db: Session, company_id: int, request_data: dict, existing_item: DcInventory = None):
    """
    Validates if the company has enough purchased capacity.
    - If existing_item is provided, it's an update; exclude its old stats from current sum.
    - If not, it's a new asset creation.
    """
    # 1. Fetch Purchased Limits from dcusage table
    limits = db.query(DcPurchase).filter(DcPurchase.company_id == company_id).first()
    
    if not limits:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No purchased capacity record found for this company. Asset provisioning blocked."
        )

    # 2. Sum current usage (excluding this item if updating)
    exclude_id = existing_item.id if existing_item else None
    usage_query = db.query(
        func.sum(DcInventory.rack_uspace).label("total_u"),
        func.sum(DcInventory.device_power).label("total_p"),
        func.sum(DcInventory.device_nports).label("total_n"),
        func.sum(DcInventory.device_sports).label("total_s")
    ).filter(DcInventory.company_id == company_id)

    if exclude_id:
        usage_query = usage_query.filter(DcInventory.id != exclude_id)

    usage = usage_query.first()

    # Normalize None to 0
    cur_u = usage.total_u or 0
    cur_p = usage.total_p or 0
    cur_n = usage.total_n or 0
    cur_s = usage.total_s or 0

    # 3. Determine Requested Values 
    # (If field is missing in update request, use existing DB value)
    req_u = request_data.get("rack_uspace") if "rack_uspace" in request_data else (existing_item.rack_uspace if existing_item else 0)
    req_p = request_data.get("device_power") if "device_power" in request_data else (existing_item.device_power if existing_item else 0)
    req_n = request_data.get("device_nports") if "device_nports" in request_data else (existing_item.device_nports if existing_item else 0)
    req_s = request_data.get("device_sports") if "device_sports" in request_data else (existing_item.device_sports if existing_item else 0)

    # 4. Perform Checks
    errors = []
    if (cur_u + req_u) > limits.uspace:
        errors.append(f"Rack Space: {cur_u + req_u}/{limits.uspace}U")
    if (cur_p + req_p) > limits.dcpower:
        errors.append(f"Power: {cur_p + req_p}/{limits.dcpower}W")
    if (cur_n + req_n) > limits.nport:
        errors.append(f"Network Ports: {cur_n + req_n}/{limits.nport}")
    if (cur_s + req_s) > limits.sport:
        errors.append(f"SAN Ports: {cur_s + req_s}/{limits.sport}")

    if errors:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Capacity Exceeded: {', '.join(errors)}"
        )


# --- VALIDATION HELPERS ---

def validate_user(db: Session, user_id: int):
    user = db.query(DcUser).filter(DcUser.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found")
    return user

def validate_company(db: Session, company_id: int):
    # Checking if company exists via users table as per your earlier logic
    company_exists = db.query(DcUser).filter(DcUser.company_id == company_id).first()
    if not company_exists:
        raise HTTPException(status_code=404, detail=f"Company {company_id} not found")
    return True

def validate_inventory(db: Session, inventory_id: int):
    inventory = db.query(DcInventory).filter(DcInventory.id == inventory_id).first()
    if not inventory:
        raise HTTPException(status_code=404, detail=f"Inventory item {inventory_id} not found")
    return inventory


# --- CRUD OPERATIONS ---

def create_dc_inventory(db: Session, request: DcInvBase, current_user: dict):
    user_id = current_user.get("user_id")
    company_id = current_user.get("company_id")

    validate_user(db, user_id)
    validate_company(db, company_id)

    # 1. Capacity Check
    check_company_capacity(db, company_id, request.model_dump())

    # 2. Hostname/Serial Duplication Check
    if db.query(DcInventory).filter(DcInventory.device_hostname == request.device_hostname).first():
        raise HTTPException(status_code=400, detail="Hostname already exists in inventory.")

    if db.query(DcInventory).filter(DcInventory.device_serial == request.device_serial).first():
        raise HTTPException(status_code=400, detail="Serial number is already registered.")

    # 3. Rack Collision Check
    collision = db.query(DcInventory).filter(
        and_(
            DcInventory.rack_name == request.rack_name,
            DcInventory.rack_unit == request.rack_unit
        )
    ).first()
    if collision:
        raise HTTPException(status_code=400, detail=f"Rack {request.rack_name} Unit {request.rack_unit} is occupied.")

    # 4. Create Record
    new_inventory = DcInventory(
        **request.model_dump(),
        user_id=user_id,
        company_id=company_id
    )
    
    db.add(new_inventory)
    db.commit()
    db.refresh(new_inventory)
    return new_inventory


def get_dc_inventory(db: Session, current_user: dict):
    company_id = current_user.get("company_id")
    inventory = db.query(DcInventory).filter(DcInventory.company_id == company_id).all()
    if not inventory:
        raise HTTPException(status_code=404, detail="No inventory found for this company.")
    return inventory


def update_dc_inventory(db: Session, id: int, request: DcInvUpdate, current_user: dict):
    company_id = current_user.get("company_id")
    inventory = validate_inventory(db, id)
    
    # Get only the fields provided in the request
    update_data = request.model_dump(exclude_unset=True)

    # 1. Capacity Check (Pass current item to exclude its old stats from the math)
    check_company_capacity(db, company_id, update_data, existing_item=inventory)

    # 2. Duplication Checks for updated fields
    if "device_hostname" in update_data:
        if db.query(DcInventory).filter(and_(DcInventory.device_hostname == update_data["device_hostname"], DcInventory.id != id)).first():
            raise HTTPException(status_code=400, detail="Hostname already exists.")
            
    if "device_serial" in update_data:
        if db.query(DcInventory).filter(and_(DcInventory.device_serial == update_data["device_serial"], DcInventory.id != id)).first():
            raise HTTPException(status_code=400, detail="Serial number already exists.")

    # 3. Apply updates
    for key, value in update_data.items():
        setattr(inventory, key, value)

    db.commit()
    db.refresh(inventory)
    return {"message": "Inventory details updated successfully"}


def delete_dc_inventory(db: Session, id: int, current_user: dict):
    # Ensure asset belongs to the company before deleting
    company_id = current_user.get("company_id")
    inventory = db.query(DcInventory).filter(
        and_(DcInventory.id == id, DcInventory.company_id == company_id)
    ).first()
    
    if not inventory:
        raise HTTPException(status_code=404, detail="Asset not found or unauthorized.")

    db.delete(inventory)
    db.commit()
    return {"message": "Inventory deleted successfully"}