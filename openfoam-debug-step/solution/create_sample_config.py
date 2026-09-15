"""Create OpenFOAM sampling configuration for velocity near the lower wall."""

sample_config = """\
FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      sample;
}

type            sets;
libs            (sampling);
interpolationScheme cellPoint;
setFormat       raw;
writeControl    writeTime;

sets
(
    nearLowerWall
    {
        type    uniform;
        axis    x;
        start   (0.001 -0.023 0);
        end     (0.280 -0.023 0);
        nPoints 200;
    }
);

fields          (U);
"""

with open('/app/pitzDaily/system/sample', 'w') as f:
    f.write(sample_config)
