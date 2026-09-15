 *
 * Generates stress-test TACKY IR programs as JSON.
 * Usage: gen_stress_ir <program_name>
 * Available: spill_cascade, nested_loop_pressure
 */

#include <stdio.h>
#include <string.h>
#include <stdlib.h>

static void gen_spill_cascade(void)
{
    int i;

    printf("{\n");
    printf("  \"name\": \"spill_cascade\",\n");
    printf("  \"functions\": [{\n");
    printf("    \"name\": \"target\",\n");
    printf("    \"params\": [],\n");
    printf("    \"return_class\": \"gp\",\n");
    printf("    \"blocks\": [{\n");
    printf("      \"label\": \"entry\",\n");
    printf("      \"instrs\": [\n");

    for (i = 1; i <= 16; i++)
        printf("        {\"op\": \"const\", \"dst\": \"g%d\", \"class\": \"gp\", \"val\": %d},\n", i, i);

    for (i = 1; i <= 16; i++)
        printf("        {\"op\": \"const\", \"dst\": \"x%d\", \"class\": \"xmm\", \"val\": %d.0},\n", i, i);

    printf("        {\"op\": \"add\", \"dst\": \"gsum0\", \"class\": \"gp\", \"src1\": \"g1\", \"src2\": \"g2\"},\n");
    for (i = 1; i <= 14; i++)
        printf("        {\"op\": \"add\", \"dst\": \"gsum%d\", \"class\": \"gp\", \"src1\": \"gsum%d\", \"src2\": \"g%d\"},\n",
               i, i - 1, i + 2);

    printf("        {\"op\": \"add\", \"dst\": \"xsum0\", \"class\": \"xmm\", \"src1\": \"x1\", \"src2\": \"x2\"},\n");
    for (i = 1; i <= 14; i++)
        printf("        {\"op\": \"add\", \"dst\": \"xsum%d\", \"class\": \"xmm\", \"src1\": \"xsum%d\", \"src2\": \"x%d\"},\n",
               i, i - 1, i + 2);

    printf("        {\"op\": \"dbl2int\", \"dst\": \"xconv\", \"class\": \"gp\", \"src1\": \"xsum14\"},\n");
    printf("        {\"op\": \"add\", \"dst\": \"result\", \"class\": \"gp\", \"src1\": \"gsum14\", \"src2\": \"xconv\"},\n");
    printf("        {\"op\": \"ret\", \"src1\": \"result\"}\n");

    printf("      ]\n");
    printf("    }]\n");
    printf("  }]\n");
    printf("}\n");
}

static void gen_nested_loop_pressure(void)
{
    printf("{\n");
    printf("  \"name\": \"nested_loop_pressure\",\n");
    printf("  \"functions\": [{\n");
    printf("    \"name\": \"target\",\n");
    printf("    \"params\": [],\n");
    printf("    \"return_class\": \"gp\",\n");
    printf("    \"blocks\": [\n");

    printf("      {\n");
    printf("        \"label\": \"entry\",\n");
    printf("        \"instrs\": [\n");
    printf("          {\"op\": \"const\", \"dst\": \"acc\", \"class\": \"gp\", \"val\": 0},\n");
    printf("          {\"op\": \"const\", \"dst\": \"i\", \"class\": \"gp\", \"val\": 0},\n");
    printf("          {\"op\": \"const\", \"dst\": \"outer_lim\", \"class\": \"gp\", \"val\": 4},\n");
    printf("          {\"op\": \"const\", \"dst\": \"inner_lim\", \"class\": \"gp\", \"val\": 5},\n");
    printf("          {\"op\": \"const\", \"dst\": \"one\", \"class\": \"gp\", \"val\": 1},\n");
    printf("          {\"op\": \"const\", \"dst\": \"scale\", \"class\": \"gp\", \"val\": 2},\n");
    printf("          {\"op\": \"const\", \"dst\": \"bias\", \"class\": \"gp\", \"val\": 7},\n");
    printf("          {\"op\": \"jump\", \"target\": \"outer_hdr\"}\n");
    printf("        ]\n");
    printf("      },\n");

    printf("      {\n");
    printf("        \"label\": \"outer_hdr\",\n");
    printf("        \"instrs\": [\n");
    printf("          {\"op\": \"lt\", \"dst\": \"oc\", \"class\": \"gp\", \"src1\": \"i\", \"src2\": \"outer_lim\"},\n");
    printf("          {\"op\": \"cbranch\", \"src1\": \"oc\", \"true_target\": \"inner_init\", \"false_target\": \"done\"}\n");
    printf("        ]\n");
    printf("      },\n");

    printf("      {\n");
    printf("        \"label\": \"inner_init\",\n");
    printf("        \"instrs\": [\n");
    printf("          {\"op\": \"const\", \"dst\": \"j\", \"class\": \"gp\", \"val\": 0},\n");
    printf("          {\"op\": \"jump\", \"target\": \"inner_hdr\"}\n");
    printf("        ]\n");
    printf("      },\n");

    printf("      {\n");
    printf("        \"label\": \"inner_hdr\",\n");
    printf("        \"instrs\": [\n");
    printf("          {\"op\": \"lt\", \"dst\": \"ic\", \"class\": \"gp\", \"src1\": \"j\", \"src2\": \"inner_lim\"},\n");
    printf("          {\"op\": \"cbranch\", \"src1\": \"ic\", \"true_target\": \"inner_body\", \"false_target\": \"outer_inc\"}\n");
    printf("        ]\n");
    printf("      },\n");

    printf("      {\n");
    printf("        \"label\": \"inner_body\",\n");
    printf("        \"instrs\": [\n");
    printf("          {\"op\": \"copy\", \"dst\": \"jc\", \"class\": \"gp\", \"src1\": \"j\"},\n");
    printf("          {\"op\": \"mul\", \"dst\": \"prod\", \"class\": \"gp\", \"src1\": \"jc\", \"src2\": \"scale\"},\n");
    printf("          {\"op\": \"add\", \"dst\": \"sum_v\", \"class\": \"gp\", \"src1\": \"prod\", \"src2\": \"bias\"},\n");
    printf("          {\"op\": \"copy\", \"dst\": \"ac\", \"class\": \"gp\", \"src1\": \"acc\"},\n");
    printf("          {\"op\": \"add\", \"dst\": \"acc\", \"class\": \"gp\", \"src1\": \"ac\", \"src2\": \"sum_v\"},\n");
    printf("          {\"op\": \"add\", \"dst\": \"j\", \"class\": \"gp\", \"src1\": \"j\", \"src2\": \"one\"},\n");
    printf("          {\"op\": \"jump\", \"target\": \"inner_hdr\"}\n");
    printf("        ]\n");
    printf("      },\n");

    printf("      {\n");
    printf("        \"label\": \"outer_inc\",\n");
    printf("        \"instrs\": [\n");
    printf("          {\"op\": \"add\", \"dst\": \"i\", \"class\": \"gp\", \"src1\": \"i\", \"src2\": \"one\"},\n");
    printf("          {\"op\": \"jump\", \"target\": \"outer_hdr\"}\n");
    printf("        ]\n");
    printf("      },\n");

    printf("      {\n");
    printf("        \"label\": \"done\",\n");
    printf("        \"instrs\": [\n");
    printf("          {\"op\": \"add\", \"dst\": \"result\", \"class\": \"gp\", \"src1\": \"acc\", \"src2\": \"outer_lim\"},\n");
    printf("          {\"op\": \"ret\", \"src1\": \"result\"}\n");
    printf("        ]\n");
    printf("      }\n");

    printf("    ]\n");
    printf("  }]\n");
    printf("}\n");
}

int main(int argc, char *argv[])
{
    if (argc != 2) {
        fprintf(stderr, "Usage: %s <program_name>\n", argv[0]);
        fprintf(stderr, "Available programs:\n");
        fprintf(stderr, "  spill_cascade          16 GP + 16 XMM vregs, multi-spill stress test\n");
        fprintf(stderr, "  nested_loop_pressure   Nested loops with copy chains\n");
        return 1;
    }

    if (strcmp(argv[1], "spill_cascade") == 0)
        gen_spill_cascade();
    else if (strcmp(argv[1], "nested_loop_pressure") == 0)
        gen_nested_loop_pressure();
    else {
        fprintf(stderr, "Unknown program: %s\n", argv[1]);
        return 1;
    }

    return 0;
}
