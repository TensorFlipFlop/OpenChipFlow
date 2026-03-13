#!/usr/bin/env python3
import json
import os
import sys
import glob

def validate_role_contract(contract_path):
    """
    Validates the structure of role_io_contract.json.
    """
    if not os.path.exists(contract_path):
        print(f"Error: Contract file not found: {contract_path}")
        return False

    try:
        with open(contract_path, 'r') as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in {contract_path}: {e}")
        return False

    if "schema_version" not in data:
        print("Error: Missing 'schema_version'")
        return False

    if "roles" not in data:
        print("Error: Missing 'roles' section")
        return False

    valid = True
    for role, rules in data["roles"].items():
        if "inputs" not in rules:
            print(f"Warning: Role '{role}' missing 'inputs'")
        
        if "outputs" not in rules:
            print(f"Error: Role '{role}' missing 'outputs'")
            valid = False
            continue

        for out in rules["outputs"]:
            if "pattern" not in out:
                print(f"Error: Role '{role}' output missing 'pattern'")
                valid = False
            if "description" not in out:
                print(f"Warning: Role '{role}' output '{out.get('pattern')}' missing description")

    return valid

if __name__ == "__main__":
    contract_file = "cocotb_ex/config/role_io_contract.json"
    if len(sys.argv) > 1:
        contract_file = sys.argv[1]
    
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) # projects/open-chip-flow
    full_path = os.path.join(base_dir, contract_file)

    print(f"Validating contract: {full_path}")
    if validate_role_contract(full_path):
        print("SUCCESS: Role I/O contract is valid.")
        sys.exit(0)
    else:
        print("FAILURE: Role I/O contract is invalid.")
        sys.exit(1)
