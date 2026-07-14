from rest_framework import serializers


class AdminUserTableItemSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    email = serializers.EmailField()
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    username = serializers.CharField()
    admin_role = serializers.CharField(source="profile.admin_role")
    is_active = serializers.BooleanField()
    is_staff = serializers.BooleanField()


class AdminUserTableResponseSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    message = serializers.CharField()
    data = AdminUserTableItemSerializer(many=True)
    
    
    
    
class CreateAdminRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()
    first_name = serializers.CharField(max_length=150)
    last_name = serializers.CharField(max_length=150)
    password = serializers.CharField(write_only=True)
    admin_role = serializers.ChoiceField(
        choices=[
            ("super_admin", "Super Admin"),
            ("ops_admin", "Operations Admin"),
            ("moderator", "Moderation Admin"),
            ("finance_admin", "Finance Admin"),
            ("support_admin", "Support Admin"),
        ]
    )


class CreateAdminResponseDataSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    email = serializers.EmailField()
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    admin_role = serializers.CharField()
    is_staff = serializers.BooleanField()
    is_active = serializers.BooleanField()


class CreateAdminResponseSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    message = serializers.CharField()
    data = CreateAdminResponseDataSerializer() 
    
    
    
class DeleteAdminResponseDataSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    email = serializers.EmailField()
    is_active = serializers.BooleanField()
    is_staff = serializers.BooleanField()
    admin_role = serializers.CharField()


class DeleteAdminResponseSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    message = serializers.CharField()
    data = DeleteAdminResponseDataSerializer()       
    
    
    
class AdminRolePermissionsResponseSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    message = serializers.CharField()
    data = serializers.DictField(
        child=serializers.ListField(
            child=serializers.CharField()
        )
    )    