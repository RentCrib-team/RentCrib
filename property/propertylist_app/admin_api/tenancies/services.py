

from .selectors import (
    get_admin_tenancies_queryset,
    get_tenancy_stats,
    serialize_admin_tenancy,
)


def get_admin_tenancy_overview_data(params):
    queryset = get_admin_tenancies_queryset(params)

    return {
        "stats": get_tenancy_stats(),
        "tenancies": [
            serialize_admin_tenancy(tenancy)
            for tenancy in queryset
        ],
    }


