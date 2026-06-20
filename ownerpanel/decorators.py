from django.contrib.auth.decorators import user_passes_test
from django.shortcuts import redirect

def owner_required(view_func):
    def check(u):
        if not u.is_authenticated:
            return False
        try:
            return hasattr(u, "ownerprofile") and u.ownerprofile.role == "OWNER" and u.ownerprofile.store_id is not None
        except Exception:
            return False
    return user_passes_test(check, login_url="/login/")(view_func)


def get_owner_store(request):
    return request.user.ownerprofile.store