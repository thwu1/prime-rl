#include <cstdio>
#include <cstdlib>
#include "predicates.hpp"

static int sign_of(double x) {
    if (x > 0.0) return 1;
    if (x < 0.0) return -1;
    return 0;
}

static int test_orient2d(const char *filename) {
    FILE *fp = fopen(filename, "r");
    if (!fp) { fprintf(stderr, "Cannot open %s\n", filename); return -1; }
    int total = 0, passed = 0;
    int idx, expected;
    double ax, ay, bx, by, cx, cy;
    while (fscanf(fp, "%d %lf %lf %lf %lf %lf %lf %d",
                  &idx, &ax, &ay, &bx, &by, &cx, &cy, &expected) == 8) {
        double pa[2] = {ax, ay}, pb[2] = {bx, by}, pc[2] = {cx, cy};
        int got = sign_of(orient2d(pa, pb, pc));
        total++;
        if (got == expected) { passed++; }
        else { fprintf(stderr, "orient2d FAIL #%d: expected %d got %d\n", idx, expected, got); }
    }
    fclose(fp);
    printf("orient2d: %d/%d\n", passed, total);
    return passed == total ? 0 : 1;
}

static int test_orient3d(const char *filename) {
    FILE *fp = fopen(filename, "r");
    if (!fp) { fprintf(stderr, "Cannot open %s\n", filename); return -1; }
    int total = 0, passed = 0;
    int idx, expected;
    double ax,ay,az, bx,by,bz, cx,cy,cz, dx,dy,dz;
    while (fscanf(fp, "%d %lf %lf %lf %lf %lf %lf %lf %lf %lf %lf %lf %lf %d",
                  &idx, &ax,&ay,&az, &bx,&by,&bz, &cx,&cy,&cz, &dx,&dy,&dz, &expected) == 14) {
        double pa[3]={ax,ay,az}, pb[3]={bx,by,bz}, pc[3]={cx,cy,cz}, pd[3]={dx,dy,dz};
        int got = sign_of(orient3d(pa, pb, pc, pd));
        total++;
        if (got == expected) { passed++; }
        else { fprintf(stderr, "orient3d FAIL #%d: expected %d got %d\n", idx, expected, got); }
    }
    fclose(fp);
    printf("orient3d: %d/%d\n", passed, total);
    return passed == total ? 0 : 1;
}

static int test_incircle(const char *filename) {
    FILE *fp = fopen(filename, "r");
    if (!fp) { fprintf(stderr, "Cannot open %s\n", filename); return -1; }
    int total = 0, passed = 0;
    int idx, expected;
    double ax,ay, bx,by, cx,cy, dx,dy;
    while (fscanf(fp, "%d %lf %lf %lf %lf %lf %lf %lf %lf %d",
                  &idx, &ax,&ay, &bx,&by, &cx,&cy, &dx,&dy, &expected) == 10) {
        double pa[2]={ax,ay}, pb[2]={bx,by}, pc[2]={cx,cy}, pd[2]={dx,dy};
        int got = sign_of(incircle(pa, pb, pc, pd));
        total++;
        if (got == expected) { passed++; }
        else { fprintf(stderr, "incircle FAIL #%d: expected %d got %d\n", idx, expected, got); }
    }
    fclose(fp);
    printf("incircle: %d/%d\n", passed, total);
    return passed == total ? 0 : 1;
}

static int test_insphere(const char *filename) {
    FILE *fp = fopen(filename, "r");
    if (!fp) { fprintf(stderr, "Cannot open %s\n", filename); return -1; }
    int total = 0, passed = 0;
    int idx, expected;
    double ax,ay,az, bx,by,bz, cx,cy,cz, dx,dy,dz, ex,ey,ez;
    while (fscanf(fp, "%d %lf %lf %lf %lf %lf %lf %lf %lf %lf %lf %lf %lf %lf %lf %lf %d",
                  &idx, &ax,&ay,&az, &bx,&by,&bz, &cx,&cy,&cz, &dx,&dy,&dz, &ex,&ey,&ez, &expected) == 17) {
        double pa[3]={ax,ay,az}, pb[3]={bx,by,bz}, pc[3]={cx,cy,cz};
        double pd[3]={dx,dy,dz}, pe[3]={ex,ey,ez};
        int got = sign_of(insphere(pa, pb, pc, pd, pe));
        total++;
        if (got == expected) { passed++; }
        else { fprintf(stderr, "insphere FAIL #%d: expected %d got %d\n", idx, expected, got); }
    }
    fclose(fp);
    printf("insphere: %d/%d\n", passed, total);
    return passed == total ? 0 : 1;
}

int main() {
    predicates_init();

    int failures = 0;
    failures += test_orient2d("/app/data/orient2d.txt");
    failures += test_orient3d("/app/data/orient3d.txt");
    failures += test_incircle("/app/data/incircle.txt");
    failures += test_insphere("/app/data/insphere.txt");

    if (failures == 0) {
        printf("ALL TESTS PASSED\n");
        return 0;
    } else {
        printf("SOME TESTS FAILED\n");
        return 1;
    }
}
