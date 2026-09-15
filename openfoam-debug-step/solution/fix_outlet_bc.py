"""Fix the outlet boundary condition for velocity from fixedValue to zeroGradient."""

with open('/app/pitzDaily/0/U', 'r') as f:
    content = f.read()

# The outlet uses fixedValue uniform (0 0 0) which prevents mass from
# leaving the domain in an incompressible simulation. Replace with
# zeroGradient to allow developed flow to exit freely.
old_block = """    outlet
    {
        type            fixedValue;
        value           uniform (0 0 0);
    }"""

new_block = """    outlet
    {
        type            zeroGradient;
    }"""

content = content.replace(old_block, new_block)

with open('/app/pitzDaily/0/U', 'w') as f:
    f.write(content)
