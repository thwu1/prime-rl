/*-----------------------------------------------------------------------*/
/* Program: STREAM                                                       */
/* Revision: $Id: stream.c,v 5.10 2013/01/17 16:01:06 mccalpin Exp $    */
/* Original code developed by John D. McCalpin                           */
/* Programmers: John D. McCalpin                                         */
/*              Joe R. Zagar                                             */
/*                                                                       */
/* This program measures memory transfer rates in MB/s for simple        */
/* computational kernels coded in C.                                     */
/*-----------------------------------------------------------------------*/
/* Copyright 1991-2013: John D. McCalpin                                 */
/*-----------------------------------------------------------------------*/
/* License:                                                              */
/*  1. You are free to use this program and/or to redistribute           */
/*     this program.                                                     */
/*  2. You are free to modify this program for your own use,             */
/*     including commercial use, subject to the publication              */
/*     restrictions in item 3.                                           */
/*  3. Use of this program or creation of derived works based on this    */
/*     program constitutes acceptance of these licensing restrictions.    */
/*  4. Absolutely no warranty is expressed or implied.                   */
/*-----------------------------------------------------------------------*/
# include <stdio.h>
# include <unistd.h>
# include <math.h>
# include <float.h>
# include <limits.h>
# include <sys/time.h>

/*-----------------------------------------------------------------------
 * INSTRUCTIONS:
 *
 *	1) STREAM requires different amounts of memory to run on different
 *           systems, depending on both the system cache size(s) and the
 *           granularity of the system timer.
 *     You should adjust the value of 'STREAM_ARRAY_SIZE' (below)
 *           to meet *both* of the following criteria:
 *       (a) Each array must be at least 4 times the size of the
 *           available cache memory.
 *       (b) The size should be large enough so that the 'timing calibration'
 *           output by the program is at least 20 clock-ticks.
 *
 *      Array size can be set at compile time without modifying the source
 *          code for the (many) compilers that support preprocessor definitions
 *          on the compile line.  E.g.,
 *                gcc -O -DSTREAM_ARRAY_SIZE=100000000 stream.c -o stream.100M
 */
#ifndef STREAM_ARRAY_SIZE
#   define STREAM_ARRAY_SIZE	10000000
#endif

#ifdef NTIMES
#if NTIMES<=1
#   define NTIMES	10
#endif
#endif
#ifndef NTIMES
#   define NTIMES	10
#endif

#ifndef OFFSET
#   define OFFSET	0
#endif

# define HLINE "-------------------------------------------------------------\n"

# ifndef MIN
# define MIN(x,y) ((x)<(y)?(x):(y))
# endif
# ifndef MAX
# define MAX(x,y) ((x)>(y)?(x):(y))
# endif

#ifndef STREAM_TYPE
#define STREAM_TYPE double
#endif

static STREAM_TYPE	a[STREAM_ARRAY_SIZE+OFFSET],
			b[STREAM_ARRAY_SIZE+OFFSET],
			c[STREAM_ARRAY_SIZE+OFFSET];

static double	avgtime[4] = {0}, maxtime[4] = {0},
		mintime[4] = {FLT_MAX,FLT_MAX,FLT_MAX,FLT_MAX};

static char	*label[4] = {"Copy:      ", "Scale:     ",
    "Add:       ", "Triad:     "};

static double	bytes[4] = {
    2 * sizeof(STREAM_TYPE) * STREAM_ARRAY_SIZE,
    2 * sizeof(STREAM_TYPE) * STREAM_ARRAY_SIZE,
    3 * sizeof(STREAM_TYPE) * STREAM_ARRAY_SIZE,
    3 * sizeof(STREAM_TYPE) * STREAM_ARRAY_SIZE
    };

extern double mysecond();
extern void checkSTREAMresults();
#ifdef TUNED
extern void tuned_STREAM_Copy();
extern void tuned_STREAM_Scale(STREAM_TYPE scalar);
extern void tuned_STREAM_Add();
extern void tuned_STREAM_Triad(STREAM_TYPE scalar);
#endif
#ifdef _OPENMP
extern int omp_get_num_threads();
#endif
int
main()
    {
    int			quantum, checktick();
    int			BytesPerWord;
    int			k;
    ssize_t		j;
    STREAM_TYPE		scalar;
    double		t, times[4][NTIMES];

    /* --- SETUP --- determine precision and check timing --- */

    printf(HLINE);
    printf("STREAM version $Revision: 5.10 $\n");
    printf(HLINE);
    BytesPerWord = sizeof(STREAM_TYPE);
    printf("This system uses %d bytes per array element.\n",
	BytesPerWord);

    printf(HLINE);

    printf("Array size = %llu (elements), Offset = %d (elements)\n" , (unsigned long long) STREAM_ARRAY_SIZE, OFFSET);
    printf("Memory per array = %.1f MiB (= %.1f GiB).\n",
	BytesPerWord * ( (double) STREAM_ARRAY_SIZE / 1024.0/1024.0),
	BytesPerWord * ( (double) STREAM_ARRAY_SIZE / 1024.0/1024.0/1024.0));
    printf("Total memory required = %.1f MiB (= %.1f GiB).\n",
	(3.0 * BytesPerWord) * ( (double) STREAM_ARRAY_SIZE / 1024.0/1024.),
	(3.0 * BytesPerWord) * ( (double) STREAM_ARRAY_SIZE / 1024.0/1024./1024.));
    printf("Each kernel will be executed %d times.\n", NTIMES);
    printf(" The *best* time for each kernel (excluding the first iteration)\n");
    printf(" will be used to compute the reported bandwidth.\n");

#ifdef _OPENMP
    printf(HLINE);
#pragma omp parallel
    {
#pragma omp master
	{
	    k = omp_get_num_threads();
	    printf ("Number of Threads requested = %i\n",k);
        }
    }
#endif

#ifdef _OPENMP
	k = 0;
#pragma omp parallel
#pragma omp atomic
		k++;
    printf ("Number of Threads counted = %i\n",k);
#endif

    /* Get initial value for system clock. */
#pragma omp parallel for
    for (j=0; j<STREAM_ARRAY_SIZE; j++) {
	    a[j] = 1.0;
	    b[j] = 2.0;
	    c[j] = 0.0;
	}

    printf(HLINE);

    if  ( (quantum = checktick()) >= 1)
	printf("Your clock granularity/precision appears to be "
	    "%d microseconds.\n", quantum);
    else {
	printf("Your clock granularity appears to be "
	    "less than one microsecond.\n");
	quantum = 1;
    }

    t = mysecond();
#pragma omp parallel for
    for (j = 0; j < STREAM_ARRAY_SIZE; j++)
		a[j] = 2.0E0 * a[j];
    t = 1.0E6 * (mysecond() - t);

    printf("Each test below will take on the order"
	" of %d microseconds.\n", (int) t  );
    printf("   (= %d clock ticks)\n", (int) (t/quantum) );
    printf("Increase the size of the arrays if this shows that\n");
    printf("you are not getting at least 20 clock ticks per test.\n");

    printf(HLINE);

    printf("WARNING -- The above is only a rough guideline.\n");
    printf("For best results, please be sure you know the\n");
    printf("precision of your system timer.\n");
    printf(HLINE);

    /*	--- MAIN LOOP --- repeat test cases NTIMES times --- */

    scalar = 3.0;
    for (k=0; k<NTIMES; k++)
	{
	times[0][k] = mysecond();
#ifdef TUNED
        tuned_STREAM_Copy();
#else
#pragma omp parallel for
	for (j=0; j<STREAM_ARRAY_SIZE; j++)
	    c[j] = a[j];
#endif
	times[0][k] = mysecond() - times[0][k];

	times[1][k] = mysecond();
#ifdef TUNED
        tuned_STREAM_Scale(scalar);
#else
#pragma omp parallel for
	for (j=0; j<STREAM_ARRAY_SIZE; j++)
	    b[j] = scalar*c[j];
#endif
	times[1][k] = mysecond() - times[1][k];

	times[2][k] = mysecond();
#ifdef TUNED
        tuned_STREAM_Add();
#else
#pragma omp parallel for
	for (j=0; j<STREAM_ARRAY_SIZE; j++)
	    c[j] = a[j]+b[j];
#endif
	times[2][k] = mysecond() - times[2][k];

	times[3][k] = mysecond();
#ifdef TUNED
        tuned_STREAM_Triad(scalar);
#else
#pragma omp parallel for
	for (j=0; j<STREAM_ARRAY_SIZE; j++)
	    a[j] = b[j]+scalar*c[j];
#endif
	times[3][k] = mysecond() - times[3][k];
	}

    /*	--- SUMMARY --- */

    for (k=1; k<NTIMES; k++) /* note -- skip first iteration */
	{
	for (j=0; j<4; j++)
	    {
	    avgtime[j] = avgtime[j] + times[j][k];
	    mintime[j] = MIN(mintime[j], times[j][k]);
	    maxtime[j] = MAX(maxtime[j], times[j][k]);
	    }
	}

    printf("Function    Best Rate MB/s  Avg time     Min time     Max time\n");
    for (j=0; j<4; j++) {
		avgtime[j] = avgtime[j]/(double)(NTIMES-1);

		printf("%s%12.1f  %11.6f  %11.6f  %11.6f\n", label[j],
	       1.0E-06 * bytes[j]/mintime[j],
	       avgtime[j],
	       mintime[j],
	       maxtime[j]);
    }
    printf(HLINE);

    /* --- Check Results --- */
    checkSTREAMresults();
    printf(HLINE);

    return 0;
}

# define	M	20

int
checktick()
    {
    int		i, minDelta, Delta;
    double	t1, t2, timesfound[M];

    for (i = 0; i < M; i++) {
	t1 = mysecond();
	while( ((t2=mysecond()) - t1) < 1.0E-6 )
	    ;
	timesfound[i] = t1 = t2;
	}

    minDelta = 1000000;
    for (i = 1; i < M; i++) {
	Delta = (int)( 1.0E6 * (timesfound[i]-timesfound[i-1]));
	minDelta = MIN(minDelta, MAX(Delta,0));
	}

   return(minDelta);
    }

#include <sys/time.h>

double mysecond()
{
        struct timeval tp;
        struct timezone tzp;
        int i;

        i = gettimeofday(&tp,&tzp);
        return ( (double) tp.tv_sec + (double) tp.tv_usec * 1.e-6 );
}

#ifndef abs
#define abs(a) ((a) >= 0 ? (a) : -(a))
#endif
void checkSTREAMresults ()
{
	STREAM_TYPE aj,bj,cj,scalar;
	STREAM_TYPE aSumErr,bSumErr,cSumErr;
	STREAM_TYPE aAvgErr,bAvgErr,cAvgErr;
	double epsilon;
	ssize_t	j;
	int	k,ierr,err;

    /* reproduce initialization */
	aj = 1.0;
	bj = 2.0;
	cj = 0.0;
    /* a[] is modified during timing check */
	aj = 2.0E0 * aj;
    /* now execute timing loop */
	scalar = 3.0;
	for (k=0; k<NTIMES; k++)
        {
            cj = aj;
            bj = scalar*cj;
            cj = aj+bj;
            aj = bj+scalar*cj;
        }

	/* accumulate deltas between observed and expected results */
	aSumErr = 0.0;
	bSumErr = 0.0;
	cSumErr = 0.0;
	for (j=0; j<STREAM_ARRAY_SIZE; j++) {
		aSumErr += abs(a[j] - aj);
		bSumErr += abs(b[j] - bj);
		cSumErr += abs(c[j] - cj);
	}
	aAvgErr = aSumErr / (STREAM_TYPE) STREAM_ARRAY_SIZE;
	bAvgErr = bSumErr / (STREAM_TYPE) STREAM_ARRAY_SIZE;
	cAvgErr = cSumErr / (STREAM_TYPE) STREAM_ARRAY_SIZE;

	if (sizeof(STREAM_TYPE) == 4) {
		epsilon = 1.e-6;
	}
	else if (sizeof(STREAM_TYPE) == 8) {
		epsilon = 1.e-13;
	}
	else {
		printf("WEIRD: sizeof(STREAM_TYPE) = %lu\n",sizeof(STREAM_TYPE));
        epsilon = 1.e-6;
	}

	err = 0;
	if (abs(aAvgErr/aj) > epsilon) {
		err++;
		printf ("Failed Validation on array a[], AvgRelAbsErr=%e\n",abs(aAvgErr));
		printf ("     Expected Value: %e, AvgAbsErr: %e, MaxRelErr: %e\n",aj,aAvgErr,aAvgErr);
	}
	if (abs(bAvgErr/bj) > epsilon) {
		err++;
		printf ("Failed Validation on array b[], AvgRelAbsErr=%e\n",abs(bAvgErr));
		printf ("     Expected Value: %e, AvgAbsErr: %e, MaxRelErr: %e\n",bj,bAvgErr,bAvgErr);
	}
	if (abs(cAvgErr/cj) > epsilon) {
		err++;
		printf ("Failed Validation on array c[], AvgRelAbsErr=%e\n",abs(cAvgErr));
		printf ("     Expected Value: %e, AvgAbsErr: %e, MaxRelErr: %e\n",cj,cAvgErr,cAvgErr);
	}
	if (err == 0) {
		printf ("Solution Validates: avg error less than %e on all three arrays\n",epsilon);
	}
}
