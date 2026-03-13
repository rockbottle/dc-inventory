from sqlalchemy.orm.session import Session
from schemas import DcInvBase, DcInvUpdate
from db.models import DcInventory, DcUser
from fastapi import HTTPException, status

def check_dc_inventory(data: dict):
    """
    Validate DC inventory fields to ensure they are non-zero and positive.
    """
    for field in ['rack_uspace', 'device_power']:
        if data.get(field) is None or data[field] <= 0:
            raise ValueError(f"{field} must be greater than 0.")


def validate_user(db: Session, user_id: int):
    user = db.query(DcUser).filter(DcUser.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with id {user_id} not found"
        )
    return user

def validate_company(db: Session, company_id: int):
    company = db.query(DcUser).filter(DcUser.company_id == company_id).first()
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Company with id {company_id} not found"
        )
    return company

def validate_inventory(db: Session, inventory_id: int):
    inventory = db.query(DcInventory).filter(DcInventory.id == inventory_id).first()
    if not inventory:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Inventory with id {inventory_id} not found"
        )
    return inventory

def create_dc_inventory(db: Session, request: DcInvBase, current_user: dict):
    user_id = current_user.get("user_id")
    company_id = current_user.get("company_id")

    validate_user(db, user_id)
    validate_company(db, company_id)

    new_inventory = DcInventory(
        device_type=request.device_type,
        device_hostname=request.device_hostname,
        device_model=request.device_model,
        device_serial=request.device_serial,
        rack_name=request.rack_name,
        rack_unit=request.rack_unit,
        rack_uspace=request.rack_uspace,
        device_power=request.device_power,
        device_nports=request.device_nports,
        device_sports=request.device_sports,
        power_status=request.power_status,
        device_status=request.device_status,
        user_id=user_id,
        company_id=company_id
    )
    try:
        check_dc_inventory(request.model_dump())
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    db.add(new_inventory)
    db.commit()
    db.refresh(new_inventory)
    return new_inventory

def get_dc_inventory(db: Session, current_user: dict):
    company_id = current_user.get("company_id")
    inventory = db.query(DcInventory).filter(DcInventory.company_id == company_id).all()
    if not inventory:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No inventory found for company with id {company_id}"
        )
    return inventory

def update_dc_inventory(db: Session, id: int, request: DcInvUpdate, current_user: dict):
    company_id = current_user.get("company_id")
    validate_company(db, company_id)

    inventory = validate_inventory(db, id)
    update_data = request.model_dump(exclude_unset=True)

    for key, value in update_data.items():
        setattr(inventory, key, value)

    db.commit()
    return {"message": "Inventory details updated successfully"}

def delete_dc_inventory(db: Session, id: int, current_user: dict):
    user_id = current_user.get("user_id")
    company_id = current_user.get("company_id")

    validate_user(db, user_id)
    validate_company(db, company_id)

    inventory = validate_inventory(db, id)
    db.delete(inventory)
    db.commit()
    return {"message": "Inventory deleted successfully"}
