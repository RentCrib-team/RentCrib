from .selectors import (
    get_admin_users_queryset,
    get_admin_role_permissions,
)
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from propertylist_app.models import UserProfile







def get_admin_users_table_data():
    return get_admin_users_queryset()
  
  
  
def create_admin_user(validated_data):
    email = validated_data["email"].lower().strip()

    if User.objects.filter(email__iexact=email).exists():
        raise ValidationError("A user with this email already exists.")

    password = validated_data["password"]

    validate_password(password)

    username = email

    user = User.objects.create_user(
        username=username,
        email=email,
        first_name=validated_data["first_name"],
        last_name=validated_data["last_name"],
        password=password,
        is_staff=True,
        is_active=True,
    )

    profile, _ = UserProfile.objects.get_or_create(user=user)

    profile.admin_role = validated_data["admin_role"]
    profile.save(update_fields=["admin_role"])

    return {
        "id": user.id,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "admin_role": profile.admin_role,
        "is_staff": user.is_staff,
        "is_active": user.is_active,
    }  
    
    
def delete_admin_user(admin_user_id):
    try:
        user = User.objects.select_related("profile").get(id=admin_user_id)
    except User.DoesNotExist:
        raise ValidationError("Admin user not found.")

    profile = getattr(user, "profile", None)

    if not user.is_staff or not profile or not profile.admin_role:
        raise ValidationError("This user is not an admin user.")

    user.is_active = False
    user.is_staff = False
    user.save(update_fields=["is_active", "is_staff"])

    profile.admin_role = ""
    profile.save(update_fields=["admin_role"])

    return {
        "id": user.id,
        "email": user.email,
        "is_active": user.is_active,
        "is_staff": user.is_staff,
        "admin_role": profile.admin_role,
    }    
    
    
def get_admin_permissions_data():
    return get_admin_role_permissions()    