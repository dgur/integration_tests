# -*- coding: utf-8 -*-
import pytest
import time
from cfme.common.vm import VM
from cfme.exceptions import CFMEException
from cfme.infrastructure.provider.scvmm import SCVMMProvider
from utils import testgen
from utils.generators import random_vm_name
from utils.log import logger
from utils.wait import TimedOutError
from cfme import test_requirements


def pytest_generate_tests(metafunc):
    # Filter out providers without provisioning data or hosts defined
    argnames, argvalues, idlist = testgen.all_providers(metafunc)
    testgen.parametrize(metafunc, argnames, argvalues, ids=idlist, scope="module")


@pytest.fixture(scope="module")
def vm_name():
    return random_vm_name("dscvry")


@pytest.fixture(scope="module")
def vm_crud(vm_name, provider):
    return VM.factory(vm_name, provider)


def if_scvmm_refresh_provider(provider):
    # No eventing from SCVMM so force a relationship refresh
    if isinstance(provider, SCVMMProvider):
        provider.refresh_provider_relationships()


def wait_for_vm_state_changes(vm, timeout=600):

    count = 0
    while count < timeout:
        try:
            vm_state = vm.find_quadicon(from_any_provider=True).data['state'].lower()
            logger.info("Quadicon state for %s is %s", vm.name, repr(vm_state))
            if "archived" in vm_state:
                return True
            elif "orphaned" in vm_state:
                raise CFMEException("VM should be Archived but it is Orphaned now.")
        except Exception as e:
            logger.exception(e)
            pass
        time.sleep(15)
        count += 15
    if count > timeout:
        raise CFMEException("VM should be Archived but it is Orphaned now.")


@pytest.mark.tier(2)
@test_requirements.discovery
def test_vm_discovery(request, setup_provider, provider, vm_crud):
    """ Tests whether cfme will discover a vm change (add/delete) without being manually refreshed.

    Prerequisities:
        * Desired provider set up

    Steps:
        * Create a virtual machine on the provider.
        * Wait for the VM to appear
        * Delete the VM from the provider (not using CFME)
        * Wait for the VM to become Archived.

    Metadata:
        test_flag: discovery
    """

    @request.addfinalizer
    def _cleanup():
        vm_crud.delete_from_provider()
        if_scvmm_refresh_provider(provider)

    vm_crud.create_on_provider(allow_skip="default")
    if_scvmm_refresh_provider(provider)

    try:
        vm_crud.wait_to_appear(timeout=600, load_details=False)
    except TimedOutError:
        pytest.fail("VM was not found in CFME")
    vm_crud.delete_from_provider()
    if_scvmm_refresh_provider(provider)
    wait_for_vm_state_changes(vm_crud)
